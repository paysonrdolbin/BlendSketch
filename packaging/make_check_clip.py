"""Write a one-second ProRes 422 HQ test clip, used by CI to check the packaged app decodes ProRes.

Usage: python packaging/make_check_clip.py out.mov
"""

import sys

import av
import numpy as np


def main(path: str):
    c = av.open(path, "w")
    s = c.add_stream("prores_ks", rate=24)
    s.width, s.height, s.pix_fmt = 640, 360, "yuv422p10le"
    for i in range(24):
        f = av.VideoFrame.from_ndarray(np.full((360, 640, 3), i * 10, np.uint8), format="rgb24")
        for p in s.encode(f):
            c.mux(p)
    for p in s.encode():
        c.mux(p)
    c.close()


if __name__ == "__main__":
    main(sys.argv[1])
