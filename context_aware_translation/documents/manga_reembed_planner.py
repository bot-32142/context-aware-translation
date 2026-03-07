from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def clamp(self, w: int, h: int) -> Box:
        return Box(
            x0=max(0, min(self.x0, w)),
            y0=max(0, min(self.y0, h)),
            x1=max(0, min(self.x1, w)),
            y1=max(0, min(self.y1, h)),
        )

    def expand(self, pad_x: int, pad_y: int, w: int, h: int) -> Box:
        return Box(
            x0=self.x0 - pad_x,
            y0=self.y0 - pad_y,
            x1=self.x1 + pad_x,
            y1=self.y1 + pad_y,
        ).clamp(w, h)

    def intersect(self, other: Box) -> Box | None:
        x0 = max(self.x0, other.x0)
        y0 = max(self.y0, other.y0)
        x1 = min(self.x1, other.x1)
        y1 = min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return None
        return Box(x0, y0, x1, y1)


@dataclass(frozen=True)
class TextRegion:
    index: int
    box: Box
    text: str


@dataclass(frozen=True)
class RegionGroup:
    members: tuple[TextRegion, ...]

    @property
    def reading_order(self) -> int:
        return min(member.index for member in self.members)

    @property
    def member_indices(self) -> tuple[int, ...]:
        return tuple(member.index for member in self.members)

    @property
    def member_boxes(self) -> tuple[Box, ...]:
        return tuple(member.box for member in self.members)

    @property
    def box(self) -> Box:
        return _union_boxes(list(self.member_boxes))


@dataclass
class MangaCropPlan:
    index: int
    reading_order: int
    member_indices: tuple[int, ...]
    member_boxes: tuple[Box, ...]
    context_box: Box
    square_box: Box
    page_src_box: Box
    dst_x: int
    dst_y: int
    crop_side: int
    detected_text: str


def _union_boxes(boxes: list[Box]) -> Box:
    if not boxes:
        raise ValueError("Cannot union empty boxes.")
    x0 = min(box.x0 for box in boxes)
    y0 = min(box.y0 for box in boxes)
    x1 = max(box.x1 for box in boxes)
    y1 = max(box.y1 for box in boxes)
    return Box(x0, y0, x1, y1)


def _merge_two_groups(a: RegionGroup, b: RegionGroup) -> RegionGroup:
    merged = sorted([*a.members, *b.members], key=lambda member: member.index)
    return RegionGroup(members=tuple(merged))


def _box_contains(outer: Box, inner: Box) -> bool:
    return outer.x0 <= inner.x0 and outer.y0 <= inner.y0 and outer.x1 >= inner.x1 and outer.y1 >= inner.y1


def _group_context_box(
    group: RegionGroup,
    *,
    page_w: int,
    page_h: int,
    context_pad_ratio: float,
    context_pad_px: int,
) -> Box:
    expanded_boxes: list[Box] = []
    for member_box in group.member_boxes:
        pad_x = int(round((member_box.width * context_pad_ratio) + context_pad_px))
        pad_y = int(round((member_box.height * context_pad_ratio) + context_pad_px))
        pad_x = min(pad_x, int(page_w * 0.18))
        pad_y = min(pad_y, int(page_h * 0.18))
        expanded_boxes.append(member_box.expand(pad_x=pad_x, pad_y=pad_y, w=page_w, h=page_h))
    return _union_boxes(expanded_boxes)


def _merge_by_components(
    groups: list[RegionGroup],
    *,
    edge_builder: Callable[[int, int], bool],
) -> tuple[list[RegionGroup], bool]:
    if len(groups) <= 1:
        return groups, False

    adjacency: list[set[int]] = [set() for _ in groups]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            if edge_builder(i, j):
                adjacency[i].add(j)
                adjacency[j].add(i)

    if not any(adjacency):
        return groups, False

    visited = [False] * len(groups)
    merged_groups: list[RegionGroup] = []
    changed = False
    for seed in range(len(groups)):
        if visited[seed]:
            continue
        visited[seed] = True
        queue = [seed]
        component = [seed]
        while queue:
            current = queue.pop()
            for nxt in adjacency[current]:
                if visited[nxt]:
                    continue
                visited[nxt] = True
                queue.append(nxt)
                component.append(nxt)

        if len(component) == 1:
            merged_groups.append(groups[component[0]])
            continue

        changed = True
        component_groups = [groups[idx] for idx in sorted(component)]
        merged = component_groups[0]
        for group in component_groups[1:]:
            merged = _merge_two_groups(merged, group)
        merged_groups.append(merged)

    merged_groups.sort(key=lambda group: group.reading_order)
    return merged_groups, changed


def _merge_groups_by_context_overlap(
    groups: list[RegionGroup],
    *,
    page_w: int,
    page_h: int,
    context_pad_ratio: float,
    context_pad_px: int,
) -> list[RegionGroup]:
    current = groups
    while True:
        contexts = [
            _group_context_box(
                group,
                page_w=page_w,
                page_h=page_h,
                context_pad_ratio=context_pad_ratio,
                context_pad_px=context_pad_px,
            )
            for group in current
        ]

        def _overlap_edge(i: int, j: int, _contexts: list[Box] = contexts) -> bool:
            return _contexts[i].intersect(_contexts[j]) is not None

        current, changed = _merge_by_components(
            current,
            edge_builder=_overlap_edge,
        )
        if not changed:
            return current


def _merge_groups_for_partial_crop_avoidance(
    groups: list[RegionGroup],
    *,
    page_w: int,
    page_h: int,
    context_pad_ratio: float,
    context_pad_px: int,
) -> list[RegionGroup]:
    current = groups
    while True:
        contexts = [
            _group_context_box(
                group,
                page_w=page_w,
                page_h=page_h,
                context_pad_ratio=context_pad_ratio,
                context_pad_px=context_pad_px,
            )
            for group in current
        ]

        def _edge_builder(
            i: int,
            j: int,
            _contexts: list[Box] = contexts,
            _current: list[RegionGroup] = current,
        ) -> bool:
            context_i = _contexts[i]
            context_j = _contexts[j]

            for box in _current[j].member_boxes:
                if context_i.intersect(box) is not None and not _box_contains(context_i, box):
                    return True
            for box in _current[i].member_boxes:
                if context_j.intersect(box) is not None and not _box_contains(context_j, box):
                    return True
            return False

        current, changed = _merge_by_components(current, edge_builder=_edge_builder)
        if not changed:
            return current


def _make_square_box(box: Box) -> Box:
    side = max(box.width, box.height)
    side = max(side, 8)
    cx = (box.x0 + box.x1) / 2.0
    cy = (box.y0 + box.y1) / 2.0
    x0 = int(round(cx - (side / 2)))
    y0 = int(round(cy - (side / 2)))
    return Box(x0, y0, x0 + side, y0 + side)


def _extract_square_crop(
    page: Image.Image,
    square_box: Box,
    *,
    source_box: Box | None = None,
) -> tuple[Image.Image, Box, int, int]:
    page_w, page_h = page.size
    page_bounds = Box(0, 0, page_w, page_h)
    src_box = source_box.intersect(page_bounds) if source_box is not None else square_box.intersect(page_bounds)

    side = square_box.width
    crop = Image.new("RGB", (side, side), (255, 255, 255))
    if src_box is None:
        return crop, Box(0, 0, 0, 0), 0, 0

    src_patch = page.crop((src_box.x0, src_box.y0, src_box.x1, src_box.y1))
    dst_x = src_box.x0 - square_box.x0
    dst_y = src_box.y0 - square_box.y0
    crop.paste(src_patch, (dst_x, dst_y))
    return crop, src_box, dst_x, dst_y


def _build_square_dependency_graph(
    plans: list[MangaCropPlan],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    plan_by_id = {plan.index: plan for plan in plans}
    incoming: dict[int, set[int]] = {plan.index: set() for plan in plans}
    outgoing: dict[int, set[int]] = {plan.index: set() for plan in plans}

    ordered = sorted(plans, key=lambda plan: (plan.reading_order, plan.index))
    for i, earlier in enumerate(ordered):
        for later in ordered[i + 1 :]:
            if plan_by_id[earlier.index].square_box.intersect(plan_by_id[later.index].square_box) is None:
                continue
            outgoing[earlier.index].add(later.index)
            incoming[later.index].add(earlier.index)
    return incoming, outgoing


def _order_plans_by_dependencies(plans: list[MangaCropPlan]) -> list[MangaCropPlan]:
    if len(plans) <= 1:
        return plans

    plan_by_id = {plan.index: plan for plan in plans}
    incoming, outgoing = _build_square_dependency_graph(plans)

    ready = [plan for plan in plans if not incoming[plan.index]]
    ready.sort(key=lambda plan: (plan.reading_order, plan.index))
    ordered: list[MangaCropPlan] = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for nxt_id in sorted(outgoing[current.index], key=lambda pid: (plan_by_id[pid].reading_order, pid)):
            incoming[nxt_id].discard(current.index)
            if not incoming[nxt_id]:
                ready.append(plan_by_id[nxt_id])
        ready.sort(key=lambda plan: (plan.reading_order, plan.index))

    if len(ordered) != len(plans):
        return sorted(plans, key=lambda plan: (plan.reading_order, plan.index))
    return ordered


def parse_regions_from_ocr_json(
    ocr_json: str | None,
    *,
    page_w: int,
    page_h: int,
) -> list[TextRegion]:
    if not ocr_json:
        return []
    payload = json.loads(ocr_json)
    if not isinstance(payload, dict):
        return []
    raw_regions = payload.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        return []

    parsed: list[TextRegion] = []
    for idx, raw in enumerate(raw_regions):
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid region at index {idx}: expected object")
        try:
            x = float(raw["x"])
            y = float(raw["y"])
            width = float(raw["width"])
            height = float(raw["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid coordinates for region at index {idx}") from exc

        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 <= width <= 1.0 and 0.0 <= height <= 1.0):
            raise ValueError("Region coordinates must be normalized to [0,1]")
        if width <= 0.0 or height <= 0.0:
            raise ValueError("Region width and height must be positive")
        if x + width > 1.0 or y + height > 1.0:
            raise ValueError("Region exceeds normalized bounds")

        x0 = int(x * page_w)
        y0 = int(y * page_h)
        x1 = int((x + width) * page_w)
        y1 = int((y + height) * page_h)
        box = Box(x0=min(x0, x1), y0=min(y0, y1), x1=max(x0, x1), y1=max(y0, y1)).clamp(page_w, page_h)
        if box.width <= 0 or box.height <= 0:
            raise ValueError("Region resolved to empty pixel box")

        raw_text = raw.get("text", "")
        parsed.append(TextRegion(index=idx, box=box, text=str(raw_text if raw_text is not None else "").strip()))

    return parsed


def build_manga_crop_plans(
    *,
    page: Image.Image,
    regions: list[TextRegion],
    context_pad_ratio: float = 0.15,
    context_pad_px: int = 6,
) -> list[MangaCropPlan]:
    if not regions:
        return []

    page_w, page_h = page.size
    grouped: list[RegionGroup] = [RegionGroup(members=(region,)) for region in regions]
    grouped = _merge_groups_by_context_overlap(
        grouped,
        page_w=page_w,
        page_h=page_h,
        context_pad_ratio=context_pad_ratio,
        context_pad_px=context_pad_px,
    )
    grouped = _merge_groups_for_partial_crop_avoidance(
        grouped,
        page_w=page_w,
        page_h=page_h,
        context_pad_ratio=context_pad_ratio,
        context_pad_px=context_pad_px,
    )
    grouped.sort(key=lambda group: group.reading_order)

    plans: list[MangaCropPlan] = []
    for plan_idx, group in enumerate(grouped, start=1):
        context_box = _group_context_box(
            group,
            page_w=page_w,
            page_h=page_h,
            context_pad_ratio=context_pad_ratio,
            context_pad_px=context_pad_px,
        )
        square_box = _make_square_box(context_box)
        _crop_image, page_src_box, dst_x, dst_y = _extract_square_crop(page, square_box, source_box=context_box)
        detected_text = "\n".join(member.text for member in group.members)
        plans.append(
            MangaCropPlan(
                index=plan_idx,
                reading_order=group.reading_order,
                member_indices=group.member_indices,
                member_boxes=group.member_boxes,
                context_box=context_box,
                square_box=square_box,
                page_src_box=page_src_box,
                dst_x=dst_x,
                dst_y=dst_y,
                crop_side=square_box.width,
                detected_text=detected_text,
            )
        )

    return _order_plans_by_dependencies(plans)


def render_live_crop(page: Image.Image, plan: MangaCropPlan) -> Image.Image:
    crop, _, _, _ = _extract_square_crop(page, plan.square_box, source_box=plan.context_box)
    return crop


def normalize_to_size(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    if img.size == (target_w, target_h):
        return img
    return ImageOps.fit(
        img,
        size=(target_w, target_h),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def crop_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def stitch_plan(*, stitched_page: Image.Image, plan: MangaCropPlan, edited_crop: Image.Image) -> None:
    if plan.page_src_box.width <= 0 or plan.page_src_box.height <= 0:
        return
    src_patch = edited_crop.crop(
        (
            plan.dst_x,
            plan.dst_y,
            plan.dst_x + plan.page_src_box.width,
            plan.dst_y + plan.page_src_box.height,
        )
    )
    stitched_page.paste(src_patch, (plan.page_src_box.x0, plan.page_src_box.y0))
