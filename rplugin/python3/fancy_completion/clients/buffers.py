from asyncio import Queue
from asyncio.locks import Event
from dataclasses import dataclass
from itertools import chain
from os import linesep
from typing import AsyncIterator, Dict, Iterator, Sequence, Set

from pynvim import Nvim
from pynvim.api.buffer import Buffer
from pynvim.api.common import NvimError

from ..shared.nvim import call, run_forever
from ..shared.parse import coalesce, find_matches, normalize
from ..shared.types import Completion, Context, Seed, Source
from .pkgs.nvim import autocmd, current_buf
from .pkgs.scheduler import schedule

NAME = "buffers"


@dataclass(frozen=True)
class Config:
    polling_rate: float
    max_length: int


def buf_gen(nvim: Nvim, bufnrs: Set[int]) -> Iterator[Buffer]:
    seen: Set[str] = set()
    if bufnrs:
        buffers: Sequence[Buffer] = nvim.api.list_bufs()
        for buf in buffers:
            if buf.number in bufnrs:
                filename = nvim.api.buf_get_name(buf)
                if filename not in seen:
                    seen.add(filename)
                    yield buf


async def buffer_chars(nvim: Nvim, buf_gen: Iterator[Buffer]) -> Sequence[str]:
    def cont() -> Sequence[str]:
        lines = tuple(
            line
            for buffer in buf_gen
            for line in nvim.api.buf_get_lines(buffer, 0, -1, True)
        )
        return lines

    try:
        lines = await call(nvim, cont)
    except NvimError:
        return ()
    else:
        chars = tuple(char for line in lines for char in chain(line, linesep))
        return chars


async def main(nvim: Nvim, chan: Queue, seed: Seed) -> Source:
    config = Config(**seed.config)
    ch = Event()
    min_length, max_length, unifying_chars = (
        seed.min_match,
        config.max_length,
        seed.unifying_chars,
    )

    bufnrs: Set[int] = set()
    words: Dict[str, str] = {}

    await autocmd(
        nvim,
        name="buffers",
        events=("TextChanged", "TextChangedI", "BufEnter"),
        arg_eval=("'add'",),
    )

    async def ooda() -> None:
        while True:
            action, *_ = await chan.get()
            if action == "add":
                bufnr = await current_buf(nvim)
                bufnrs.add(bufnr)
            elif action == "clear":
                words.clear()
                ch.set()

    async def background_update() -> None:
        async for _ in schedule(ch, min_time=0.0, max_time=config.polling_rate):
            b_gen = buf_gen(nvim, bufnrs)
            chars = await buffer_chars(nvim, b_gen)
            bufnrs.clear()
            for word in coalesce(
                chars, max_length=max_length, unifying_chars=unifying_chars
            ):
                if word not in words:
                    words[word] = normalize(word)

    async def source(context: Context) -> AsyncIterator[Completion]:
        position = context.position
        old_prefix, old_suffix = context.alnums_before, context.alnums_after
        cword, ncword = context.alnums, context.alnums_normalized

        for word in find_matches(
            cword, ncword=ncword, min_match=min_length, words=words
        ):
            yield Completion(
                position=position,
                old_prefix=old_prefix,
                new_prefix=word,
                old_suffix=old_suffix,
                new_suffix="",
            )

    run_forever(nvim, ooda)
    run_forever(nvim, background_update)
    return source
