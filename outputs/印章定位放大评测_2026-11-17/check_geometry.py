"""Check the inverse against Pillow's raster rotation on a non-square image."""
from run_scan import PROJECT
from edge_scan import source_box
from PIL import Image

crop = (120, 250, 420, 930)
mask = Image.new("L", (300, 680))
mask.paste(255, (17, 51, 231, 104))
expected = (137, 301, 351, 354)
for angle, op in ((0, None), (90, Image.Transpose.ROTATE_90), (-90, Image.Transpose.ROTATE_270)):
    view = mask if op is None else mask.transpose(op)
    normalized = tuple(v / size for v, size in zip(view.getbbox(), view.size * 2))
    result = source_box(normalized, crop, angle)
    assert all(abs(a-b) < 1e-8 for a,b in zip(expected,result)), (angle,result)
    print(angle, view.size, tuple(round(v) for v in result))
