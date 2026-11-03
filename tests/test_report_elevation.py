"""报告里「最低标高」的数值必须是米。

`Node.point` 给出的是 mm（对外单位），但 `_fmt_z()` 曾按 μm 换算，
于是任何非零标高的模型，这一行都小 1000 倍：6000 mm 显示成 `z=0.006`。

z=0 时显示 `±0.000`，看不出问题 —— 所以此前所有从地面起步的示例都撞不上，
而屋架下弦、地下室、架空平台这类模型一用就露馅。
"""

from strutkit import Model


def _level(z: float) -> Model:
    """一条位于标高 z 处的水平梁，用于触发「最低标高」这一行。"""
    m = Model()
    m.define("BEAM").add((0, 0, z), (3000, 0, z))
    return m


def _elevation_line(m: Model) -> str:
    return next(ln for ln in m.report().splitlines() if "最低标高" in ln)


def test_elevation_above_zero():
    assert "z=6.000" in _elevation_line(_level(6000.0))


def test_elevation_at_zero():
    assert "z=±0.000" in _elevation_line(_level(0.0))


def test_elevation_below_zero():
    assert "z=-3.000" in _elevation_line(_level(-3000.0))


def test_elevation_without_horizontal_members():
    """另一条分支（z=... 处无水平构件：OK）用的是同一个 _fmt_z，也得对"""
    m = Model()
    m.define("COL").add((0, 0, 6000.0), (0, 0, 9000.0))     # 只有竖直构件
    assert "z=6.000" in _elevation_line(m)
