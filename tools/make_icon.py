"""生成「书签工具」应用图标。

设计：品牌蓝圆角底 + 白色书签轮廓 + 蓝色心跳脉冲线。
脉冲线代表"检测链接存活"，与产品核心能力呼应。

先 4 倍超采样渲染再降采样，保证小尺寸下的边缘质量。
输出：
  resources/icon.ico   多尺寸 Windows 图标
  resources/icon.png   512×512，用于文档与「关于」界面
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

BRAND = (24, 95, 165, 255)      # #185FA5
WHITE = (255, 255, 255, 255)

# 512 基准坐标系下的图形路径
BOOKMARK = [(140, 84), (372, 84), (372, 424), (256, 350), (140, 424)]
PULSE = [(174, 252), (212, 252), (230, 210), (252, 296),
         (272, 238), (288, 252), (338, 252)]

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "resources")


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 512.0

    # 圆角背景
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(112 * s), fill=BRAND)

    # 书签主体
    d.polygon([(int(x * s), int(y * s)) for x, y in BOOKMARK], fill=WHITE)

    # 心跳脉冲线（小尺寸下省略，避免糊成一团）
    if size >= 40 * 4:
        d.line([(int(x * s), int(y * s)) for x, y in PULSE],
               fill=BRAND, width=max(2, int(18 * s)), joint="curve")
    return img


def make(size: int) -> Image.Image:
    """超采样后降采样，获得平滑边缘。"""
    big = render(size * 4)
    return big.resize((size, size), Image.LANCZOS)


def build_ico(images, path: str) -> None:
    """手写 ICO 容器（PNG 压缩条目，Vista+ 支持）。

    Pillow 12 的 ICO 多帧写入只保留首帧，因此这里直接拼字节。
    """
    import io
    import struct

    n = len(images)
    header = struct.pack("<HHH", 0, 1, n)          # reserved, type=icon, count
    entries, datas = [], []
    offset = 6 + 16 * n

    for size, img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        b = 0 if size >= 256 else size             # 256 用 0 表示
        entries.append(struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32,
                                   len(data), offset))
        datas.append(data)
        offset += len(data)

    with open(path, "wb") as f:
        f.write(header)
        for e in entries:
            f.write(e)
        for d in datas:
            f.write(d)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [(s, make(s)) for s in sizes]

    ico_path = os.path.join(OUT_DIR, "icon.ico")
    build_ico(frames, ico_path)

    png_path = os.path.join(OUT_DIR, "icon.png")
    make(512).save(png_path, format="PNG")

    print(f"ICO  -> {os.path.abspath(ico_path)}  尺寸: {sizes}")
    print(f"PNG  -> {os.path.abspath(png_path)}  512x512")
    print(f"ICO 大小: {os.path.getsize(ico_path)/1024:.1f} KB")


if __name__ == "__main__":
    main()
