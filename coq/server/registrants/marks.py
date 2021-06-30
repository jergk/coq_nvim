from typing import Iterable, Iterator, Sequence, Tuple, TypedDict
from uuid import uuid4

from pynvim.api.common import NvimError
from pynvim.api.nvim import Buffer, Nvim
from pynvim_pp.api import cur_win, win_get_buf, win_set_cursor
from pynvim_pp.lib import write
from pynvim_pp.operators import set_visual_selection

from ...registry import rpc
from ...shared.settings import Settings
from ...shared.types import Mark
from ..rt_types import Stack

_NS = uuid4().hex


class _MarkDetail(TypedDict):
    end_row: int
    end_col: int


def _ls_marks(nvim: Nvim, ns: str, buf: Buffer) -> Sequence[Mark]:
    marks: Sequence[Tuple[int, int, int, _MarkDetail]] = nvim.api.buf_get_extmarks(
        buf, ns, 0, -1, {"details": True}
    )

    def cont() -> Iterator[Mark]:
        for idx, r1, c1, details in marks:
            r2, c2 = details["end_row"], details["end_col"]
            m = Mark(idx=idx, begin=(r1, c1), end=(r2, c2), text="")
            yield m

    return sorted(cont(), key=lambda m: m.idx)


@rpc(blocking=True)
def nav_mark(nvim: Nvim, stack: Stack) -> None:
    ns = nvim.api.create_namespace(_NS)
    win = cur_win(nvim)
    buf = win_get_buf(nvim, win=win)
    marks = _ls_marks(nvim, ns=ns, buf=buf)

    mark = next(iter(marks), None)
    if mark:
        (r1, c1), (r2, c2) = mark.begin, mark.end
        if r1 == r2 and abs(c2 - c1) <= 1:
            win_set_cursor(nvim, win=win, row=r1, col=min(c1, c2))
        else:
            set_visual_selection(
                nvim, win=win, mode="v", mark1=(r1, c1), mark2=(r2, c2 - 1)
            )
            nvim.command("norm! c")

        nvim.command("startinsert")
        nvim.api.buf_del_extmark(buf, ns, mark.idx)
        write(nvim, "TODO --")
    else:
        write(nvim, "TODO --")


def mark(nvim: Nvim, settings: Settings, buf: Buffer, marks: Iterable[Mark]) -> None:
    ns = nvim.api.create_namespace(_NS)
    nvim.api.buf_clear_namespace(buf, ns, 0, -1)
    for mark in marks:
        (r1, c1), (r2, c2) = mark.begin, mark.end
        opts = {
            "end_line": r2,
            "end_col": c2,
            "hl_group": settings.display.mark_highlight_group,
        }
        try:
            nvim.api.buf_set_extmark(buf, ns, r1, c1, opts)
        except NvimError:
            print(mark, flush=True)
            raise

    write(nvim, *marks)

