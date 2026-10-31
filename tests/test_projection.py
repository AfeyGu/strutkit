"""投影方向自检

血的教训：iso 投影的 Z 轴符号写反，所有轴测图上下颠倒，
看图时「地面上的梁」其实是屋顶，「柱脚」其实是柱顶。
光看图看不出问题（货架上下都像货架），必须用坐标验证。

这里锁死三件事：
  1. iso 投影里 z 越大，屏幕位置越靠上
  2. front / side 投影同理
  3. 图上最下方的线，必须对应模型里 z 最小的地方
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strutkit.tools.dxf2svg import _fit, _project

W, H, PAD = 800, 600, 40


def _screen_y(proj, pts):
    tx, _ = _fit([("X", pts[0], pts[-1])], proj, W, H, PAD)
    return [tx(proj(p))[1] for p in pts]


def test_iso_z_goes_up():
    """z 越大，屏幕 y 越小（PIL 画布 y=0 在顶部）"""
    proj = _project("iso")
    ys = _screen_y(proj, [(0, 0, 0), (0, 0, 5000), (0, 0, 10000)])
    assert ys[0] > ys[1] > ys[2], f"iso 投影 z 方向反了：{ys}"


def test_front_z_goes_up():
    proj = _project("front")
    ys = _screen_y(proj, [(0, 0, 0), (0, 0, 5000), (0, 0, 10000)])
    assert ys[0] > ys[1] > ys[2], f"front 投影 z 方向反了：{ys}"


def test_side_z_goes_up():
    proj = _project("side")
    ys = _screen_y(proj, [(0, 0, 0), (0, 0, 5000), (0, 0, 10000)])
    assert ys[0] > ys[1] > ys[2], f"side 投影 z 方向反了：{ys}"


def test_lowest_line_on_screen_is_lowest_z():
    """图上最下方的线必须对应模型里最低的标高 —— 这是判定「货架有没有长反」的判据"""
    from strutkit.tools.dxf2svg import parse_dxf

    dxf = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "out", "rack.dxf")
    if not os.path.exists(dxf):
        import pytest
        pytest.skip("需要先跑 examples/rack_demo.py 生成 out/rack.dxf")

    lines = parse_dxf(dxf)
    proj = _project("iso")
    tx, _ = _fit(lines, proj, W, H, PAD)

    lowest = max(lines, key=lambda l: max(tx(proj(l[1]))[1], tx(proj(l[2]))[1]))
    z_low = min(lowest[1][2], lowest[2][2])
    z_min_model = min(min(a[2], b[2]) for _, a, b in lines)

    assert z_low == z_min_model, (
        f"图上最下方的线在 z={z_low}，但模型最低标高是 z={z_min_model} —— 图上下颠倒了"
    )


def test_iso_projection_is_isometric():
    """等轴测：X 与 Y 轴在屏幕上呈 ±30°，保持 30° 夹角"""
    import math
    proj = _project("iso")
    dx = proj((1000, 0, 0))
    dy = proj((0, 1000, 0))
    ang_x = math.degrees(math.atan2(dx[1], dx[0]))
    ang_y = math.degrees(math.atan2(dy[1], dy[0]))
    # 俯视等轴测：X 轴指向右下 −30°，Y 轴指向左下 −150°，Z 轴向上
    assert abs(ang_x + 30) < 0.01, f"X 轴角度 {ang_x}"
    assert abs(ang_y + 150) < 0.01, f"Y 轴角度 {ang_y}"