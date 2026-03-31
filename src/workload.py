from datetime import date, timedelta
from enum import Enum

import pandas
import plotly.express as px
import pyparsing as pp
from orgparse.date import OrgDate

ORG_DATE_FORMAT = (
    "<"
    + pp.Combine(
        pp.Word(pp.nums)
        + "-"
        + pp.Word(pp.nums)
        + "-"
        + pp.Word(pp.nums)
        + pp.Optional(" " + pp.Word(pp.alphas))
    )
    + ">"
)


EFFORT_NUMBER = pp.Combine(
    pp.Word(pp.nums) + pp.Optional("." + pp.OneOrMore(pp.Word(pp.nums)))
)

EFFORT_FORMAT = EFFORT_NUMBER + (pp.Literal("d") | pp.Literal("h"))


class TimelineState(Enum):
    NULL = ""  # Doesn't intersect
    BEGIN = "begins"  # Starts
    ONGOING = "continues"  # Started already, ends later
    END = "ends"  # Ends
    CONTAINED = "starts and ends"  # Starts and ends within the period
    UNKNOWN = "ERROR"  # Something went wrong. Possibly in my brain.


class Project:
    def __init__(self, name, start, end, effort):
        self.name = name
        self.start = parse_org_date(start)
        self.end = parse_org_date(end)
        self.effort = parse_effort(effort)
        if self.end <= self.start:
            raise Exception("Negative or 0 length projects are invalid")

    @property
    def length(self):
        return (self.end - self.start).days

    @property
    def FTE(self, hours_per_day=7.5):
        length_hours = self.length * hours_per_day
        return self.effort / length_hours

    def timeline_in_period(self, start_date, end_date):
        """For a given period of time (start_date (inclusive) to
        end_date (exclusive) report on the project timeline.

        Returns TimelineState

        """

        if self.end < start_date or self.start >= end_date:
            # Either finishes before the period, or doesn't start until after
            return TimelineState.NULL
        if self.start >= start_date and self.end < end_date:
            # Starts and ends within the period
            return TimelineState.CONTAINED
        if self.start < start_date and self.end >= end_date:
            # In progress throughout
            return TimelineState.ONGOING
        if self.start >= start_date:
            # Begins in te period
            return TimelineState.BEGIN
        if self.end < end_date:
            # Ends in the period
            return TimelineState.END
        raise Exception(
            f"Couldn't work out where the task {self} sits"
            " relative to the given range ({start_date} to {end_date})"
        )

    def as_bounded_timeline_bar(self, start=None, end=None):
        # Default to task length
        if end is None:
            end = self.end
        if start is None:
            start = self.start

        # When windowed, clamp the dates
        if self.start > start:
            start = self.start
        if self.end < end:
            end = self.end

        return dict(
            Task=self.name,
            Start=start.isoformat(),
            End=end.isoformat(),
            FTE=round(self.FTE, 2),
        )

    def __str__(self):
        return (
            f"{self.name} begins on {self.start} and ends on"
            f"{self.end} (a period of {self.length} days), requiring "
            f"{self.effort} hours of time to complete at a rate of "
            f"{self.FTE:.2f}FTE"
        )


def parse_effort(effort_str, hours_per_day=7.5):
    """Parse an effort measure

    Effort is a number followed by d or h, for days or hours.  The
    returned effort will be in hours based on the number of hourse in
    a day (hours_per_day)

    """

    components = EFFORT_FORMAT.parse_string(effort_str)
    num = float(components[0])
    mul = {"d": hours_per_day, "h": 1}[components[1]]

    return num * mul


def week_beginning_floor(d):
    return d - timedelta(days=d.weekday())


def week_beginning_ceil(d):
    return d + timedelta(days=6 - d.weekday())


def generate_gantt(projects, start, end):
    bars = []
    for p in projects:
        if p.timeline_in_period(start, end) not in [
            TimelineState.NULL,
            TimelineState.UNKNOWN,
        ]:
            bars.append(p.as_bounded_timeline_bar(start=start, end=end))
            print(bars[-1])
    fig = px.timeline(
        pandas.DataFrame(bars),
        x_start="Start",
        x_end="End",
        y="Task",
        color="FTE",
    )
    fig.update_yaxes(autorange="reversed")
    fig.write_image("fig1.png")


def generate_report(data, begin_date=None, end_date=None):
    # TODO: move to consistent start/end instead of begin/end

    # TODO: factor out the bounding/inclusion bit below so it can be
    # reused and gantt can be drawn separately

    # Set default dates if necessary, parse org dates if necessary
    if begin_date is None:
        begin_date = date.today()
    if not isinstance(begin_date, date):
        begin_date = parse_org_date(begin_date)
    if end_date is None:
        end_date = begin_date + timedelta(days=30)
    if not isinstance(end_date, date):
        end_date = parse_org_date(end_date)

    # Find the start of the beginning week and end of the ending week
    begin_date = week_beginning_floor(begin_date)
    end_date = week_beginning_ceil(end_date)

    def not_blank_row(r):
        return sum([len(i) for i in r]) > 0

    projects = [Project(*row) for row in data if not_blank_row(row)]

    generate_gantt(projects, begin_date, end_date)

    # print()
    return
    print(f"Reporting for the period between {begin_date} and {end_date}")
    print()
    cursor_date = begin_date

    while cursor_date <= end_date:
        print(f"Week beginning {cursor_date}")
        week_end = cursor_date + timedelta(days=7)

        fte_total = 0

        for p in projects:
            # FTE needs to be reduced if it starts or ends - move calc
            # into project class?
            timeline_status = p.timeline_in_period(cursor_date, week_end)
            if timeline_status == TimelineState.NULL:
                continue
            fte_total += p.FTE
            print(f"{p.name} {timeline_status.value} at {p.FTE:.2f}FTE")

        print(f" - Total: {fte_total:.2f} FTE")
        cursor_date = week_end
        print()


def parse_org_date(org_date):
    """Takes a date in org-mode format and returns a date object"""
    org_date_parsed = ORG_DATE_FORMAT.parse_string(org_date)
    return OrgDate.from_str(org_date_parsed[1]).start


def test():
    print("Parsing org date")
    print(parse_org_date("<2026-03-27>"))
    print("Parsing some effort estimates")
    for i in [
        "2d",
        "10d",
        "0.2d",
        "1.0d",
        "2h",
        "10h",
        "0.2h",
        "1.92 h",
        "1123.567 h",
    ]:
        print(f"Parsing {i} results in {parse_effort(i)}")

    print()
    print("Test with cached data")
    data = [
        ["ABC", "<2026-03-27 Fri>", "<2026-04-03 Fri>", "2d"],
        [
            "AI Automation Apprenticeship",
            "<2026-03-26 Thu>",
            "<2026-09-01 Tue>",
            "20d",
        ],
        [
            "Concrete International Offer",
            "<2026-03-28 Sat>",
            "<2026-04-01 Wed>",
            "2d",
        ],
        ["Workload Planning", "<2026-03-26 Thu>", "<2026-03-27 Fri>", "3h"],
        [
            "AI Education Bitesize",
            "<2026-03-23 Mon>",
            "<2026-04-08 Wed>",
            "1d",
        ],
        [
            "DCP for CU AI Curated Programmes",
            "<2026-03-23 Mon>",
            "<2026-04-08 Wed>",
            "5d",
        ],
        ["CU AI Playbook", "<2026-03-27 Fri>", "<2026-05-01 Fri>", "5d"],
        ["CURA Case Study", "<2026-03-27 Fri>", "<2026-07-01 Wed>", "4d"],
        ["Registry Case Study", "<2026-03-27 Fri>", "<2026-07-01 Wed>", "4d"],
        ["CEES Case Study", "<2026-03-27 Fri>", "<2026-07-01 Wed>", "4d"],
        ["AI Hackathon", "<2026-03-27 Fri>", "<2026-06-30 Tue>", "4d"],
        ["Material Audit", "<2026-03-27 Fri>", "<2026-03-28 Sat>", "2h"],
        [
            "Planning for delivery through MTI",
            "<2026-05-04 Mon>",
            "<2026-05-22 Fri>",
            "3d",
        ],
        ["", "", "", ""],
    ]
    generate_report(
        data,
        begin_date=date.today(),
        end_date=date.today() + timedelta(days=62),
    )


if __name__ == "__main__":
    test()
