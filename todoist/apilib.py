import todoist
from queue import PriorityQueue
import datetime as dt
from collections import defaultdict

TASK_WORK_MARK = "[WT]"
SCHEDULABLE_MARK = "[MT]"
MT_SCHEDULED_MARK = "[ST]"

def parse_time_from_name(s):
    return int(s[s.rfind("{") + 1: -2])

def parse_api_datetime(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except Exception as e:
            pass
    raise ValueError(f"Invalid Due Date: {s}")
"""
What's It look Like:?
Work Time:
 - Datetime
 - Duration
 - item


Schedulable:
 - Due Date
 - Task Work Times
 - item

 - iter_complete_items
 - iter_uncomplete_items
 - pull_existing_task_work_time_items
 - get_priority
 - get_status
 - create_task_work_time(int maxWorkTime)
 - update_on_calendar()

Task Work Time:
 - Datetime
 - Duration
 - Schedulable
 - checked
 - item
 - item_live?

 - parse_live_item()
 - create_item()
 - post()
 - get_name()

Scheduling:
1. Get all work times
    - A list of work time objects
2. Get schedulable items
    - A list of Schedulable objects
3. For Each Work Time:
    - Put each schedulable into a queue
    - Get a task work item for that schedulable
    - Put it back into the queue
    - Continue until Work Time is filled
    - Update each schedulable online


"""

class WorkTime:
    """Represents a period of time a user has set aside for work"""
    def __init__(self, **kwargs):
        self.item = kwargs.get("item")
        s = self.item["content"]
        self.start_dt = parse_api_datetime(self.item["due"]["date"])
        self.duration = parse_time_from_name(self.item["content"])

    def __str__(self):
        return self.item["content"] + " : " + str(self.duration) + " min"

    def __repr__(self):
        return self.__str__()
    @classmethod
    def get_work_times(cls, api):
        """Look at the Life calendar and pull items that have 'Work Time' in them"""
        life_project = get_project_by_name(api, "Life")
        work_times = api.projects.get_data(life_project["id"])["items"]
        work_times = [cls(item=w) for w in work_times if "Work Time" in  w["content"]]
        return work_times

class TaskWork:
    """Represents a concrete block of time dedicated to a task"""

    def __init__(self, **kwargs):
        if "item" in kwargs:
            self.item = kwargs.get("item")
            self.parse_item()
        else:
            self.schedulable = kwargs.get("schedulable")
            self.start_dt = kwargs.get("start_dt")
            self.duration = kwargs.get("duration")
            self.item = None

    def parse_item(self):
        self.start_dt = parse_api_datetime(self.item["due"]["date"])
        content = self.item["content"]
        multipliers = {"m": 1, "h": 60}
        self.duration = int(content[content.rindex("{") + 1 : content.rindex("}") - 1]) * multipliers[content[-2]]

    def make_api_item(self, api):
        if self.item != None:
            raise ValueError("I already have an API item!")
        due_str = self.start_dt.strftime("%Y-%m-%d at %H:%M")
        self.item = api.items.add(
            project_id=self.schedulable.item["project_id"],
            content=self.get_name(),
            due={"string": due_str},
            checked=0
        )

    def get_name(self):
        return MT_SCHEDULED_MARK + self.schedulable.name + "{" + str(self.duration) + "m}" +  f" [{self.duration}m]"

    def __str__(self):
        return self.get_name() + " @ " + self.start_dt.strftime("%Y-%m-%d %H:%M:%S")

    def __repr__(self):
        return self.__str__()

class Schedulable:
    """A thing Mindtime can schedule"""

    def __init__(self, api, **kwargs):
        if not "item" in kwargs:
            raise ValueError("Need To Provide Item for Schedulable")
        self.api = api
        self.name = kwargs.get("name", None)
        self.duration = kwargs.get("duration", None)
        self.due_dt = kwargs.get("due_dt", None)
        self.twts = []
        if "item" in kwargs:
            self.item = kwargs.get("item")
            self.__parse_item()

    def __parse_item(self):
        s = self.item["content"]
        multipliers = {"m": 1, "h": 60}
        self.duration = int(s[s.rindex("{") + 1:-2]) * multipliers[s[-2]]
        self.due_dt = parse_api_datetime(self.item["due"]["date"])
        self.name = s[len(SCHEDULABLE_MARK): s.rindex("{")]

    def get_content(self):
        return self.item["content"]
        #return SCHEDULABLE_MARK + self.name + "{" + str(self.duration) + "m}"

    def iter_unchecked(self):
        for t in self.twts:
            if t.item["checked"] == 0:
                yield t

    def iter_checked(self):
        for t in self.twts:
            if t.item["checked"] == 1:
                yield t

    def get_state(self):
        task_info = {
            "checked": sum([t.duration for t in self.iter_checked()]),
            "planned": sum([t.duration for t in self.iter_unchecked()]),
            "duration": self.duration,
            "due_dt": self.due_dt
        }
        task_info["pct_complete"] = task_info["checked"] / task_info["duration"]
        task_info["pct_scheduled"] = task_info["checked"] + task_info["planned"] / task_info["duration"]
        return task_info

    def get_priority(self):
        info = self.get_state()
        if info["pct_scheduled"] >= 1:
            return None
        return (info["pct_scheduled"], info["pct_complete"], info["due_dt"])

    def create_taskwork(self, start_dt, maxtime):
        task_info = self.get_state()
        t = min(maxtime, self.duration - task_info["planned"] - task_info["checked"])
        tw = TaskWork(schedulable=self, duration=t, start_dt=start_dt)
        self.twts.append(tw)
        return tw

    @classmethod
    def get_all_schedulables(cls, api):
        schedulables = []
        parent_tree = defaultdict(list)
        for project in api.state["projects"]:
            for item in api.projects.get_data(project["id"])["items"]:
                if item["content"].startswith(SCHEDULABLE_MARK):
                    schedulables.append(Schedulable(api, item=item))
                if item["content"].startswith(MT_SCHEDULED_MARK):
                    parent_tree[item["parent_id"]].append(TaskWork(item=item))
        for s in schedulables:
            s.twts += parent_tree.get(s.item["id"], [])
            print(s.twts)
        return schedulables

    def __str__(self):
        return f"{self.get_state()}"

    def __repr__(self):
        return self.__str__()

def get_project_by_name(api, name):
    projs = [p for p in api.state['projects'] if p['name'] == name]
    if len(projs) > 1:
        raise ValueError(f"Two projects with the same name: {name}")
    return projs[0]

def schedule_work_item(api, work_item):
    WORK_PERIOD = 55
    BREAK_PERIOD = 15
    NEW_ITEMS = []
    schedulables = list(Schedulable.get_all_schedulables(api))
    pq = PriorityQueue()
    for s in schedulables:
        pq.put( (*s.get_priority(), s) )
    sched_time = 0
    while sched_time < work_item.duration and not pq.empty():
        print(f"Scheduled Time = {sched_time}")
        period_time = 0
        while sched_time < work_item.duration and period_time < WORK_PERIOD and not pq.empty() :
            s = pq.get()[-1]
            start_dt = work_item.start_dt + dt.timedelta(seconds=60*sched_time)
            print(work_item.item["due"])
            tw = s.create_taskwork(start_dt, min(WORK_PERIOD - period_time, work_item.duration - sched_time ))
            print(f"TW: {tw}")
            tw.make_api_item(api)
            period_time += tw.duration
            sched_time += tw.duration
            prio = s.get_priority()
            if prio:
                pq.put( (*s.get_priority(), s) )
        sched_time += BREAK_PERIOD
    for s in schedulables:
        print(f"{s.item['content']} TWT: {s.twts}")
    api.commit()





if __name__ == "__main__":
    api = todoist.TodoistAPI("d5de4d255d156ecbd32f02f42afd8917f7f6ca9e")
    work_times = WorkTime.get_work_times(api)
    print(f"Work Times: {work_times}\n\n")
    schedule_work_item(api, work_times[0])

