"""One time range for the page: every 24 Hours / 7 Days / 30 Days selector in ui/src
drives the same React state, so clicking either chart's buttons switches both charts.

CI does not build the UI, so this reads the sources. For each time-range-selector it
follows the name in each button's onClick and in its 'active' class back to the
useState that owns it: a local useState, or a prop, followed to the JSX that renders
the component and passes it. A name it cannot follow fails the test rather than pass.
"""
import re
import shutil
from pathlib import Path

UI_SRC = Path(__file__).resolve().parents[2] / "ui" / "src"

SELECTOR = re.compile(r'<div className="time-range-selector">(.*?)</div>', re.S)
CLICK = re.compile(r"onClick=\{\(\) => (\w+)\((\d+)\)\}")
ACTIVE = re.compile(r"className=\{(\w+) === (\d+) \? 'active' : ''\}")
STATE = re.compile(r"const \[(\w+), (\w+)\] = useState\(")
COMPONENT = re.compile(r"^function (\w+)\((?:\{([^}]*)\})?\)", re.M)


def read_sources(src):
    return {p.name: p.read_text() for p in sorted(src.rglob("*.jsx"))}


def owner(sources, name, file, depth=0):
    """(file, state) for the useState that `name` in `file` reads or sets."""
    assert depth < 5, f"prop chain too deep at {file}:{name}"
    text = sources[file]
    for value, setter in STATE.findall(text):
        if name in (value, setter):
            return file, value
    comp = COMPONENT.search(text)
    props = [p.strip() for p in (comp.group(2) or "").split(",")] if comp else []
    assert name in props, f"{file}: {name} is neither a useState nor a prop"
    passed = [(f, m) for f, t in sources.items()
              for m in re.findall(rf"<{comp.group(1)}\b[^>]*\b{name}=\{{(\w+)\}}", t)]
    assert len(passed) == 1, f"{file}: prop {name} passed from {passed}"
    parent, arg = passed[0]
    return owner(sources, arg, parent, depth + 1)


def selectors(sources):
    """[(file, button values, set of owning states)] for every time-range selector."""
    found = []
    for file, text in sources.items():
        for block in SELECTOR.findall(text):
            clicks, active = CLICK.findall(block), ACTIVE.findall(block)
            assert [v for _, v in clicks] == [v for _, v in active], f"{file}: buttons differ"
            owners = {owner(sources, n, file) for n, _ in clicks + active}
            found.append((file, [int(v) for _, v in clicks], owners))
    return found


def test_both_charts_share_one_time_range():
    found = selectors(read_sources(UI_SRC))
    # Absent is not empty: the two charts' selectors must both be seen.
    assert sorted(f for f, _, _ in found) == ["App.jsx", "WeatherChart.jsx"]
    assert all(values == [24, 168, 720] for _, values, _ in found)
    owners = set().union(*(o for _, _, o in found))
    assert owners == {("App.jsx", "timeRange")}


def test_tripwire_weather_chart_with_its_own_state(tmp_path):
    """Positive control: WeatherChart keeping its own useState(24), as before the two
    selectors were synced, gives two owners."""
    src = tmp_path / "src"
    shutil.copytree(UI_SRC, src)
    chart = src / "components" / "WeatherChart.jsx"
    text = chart.read_text()
    head = "function WeatherChart({ timeRange, onTimeRangeChange }) {"
    assert text.count(head) == 1 and text.count("onTimeRangeChange(") == 3
    text = text.replace(head, "function WeatherChart() {\n"
                              "  const [timeRange, setTimeRange] = useState(24) // hours")
    chart.write_text(text.replace("onTimeRangeChange(", "setTimeRange("))
    owners = set().union(*(o for _, _, o in selectors(read_sources(src))))
    assert owners == {("App.jsx", "timeRange"), ("WeatherChart.jsx", "timeRange")}
