"""TOC/nav helper operations for EPUB translation flow."""

from __future__ import annotations

import xml.etree.ElementTree as _ET
from collections.abc import Set as AbstractSet
from typing import Any

import defusedxml.ElementTree as DefusedET

from context_aware_translation.documents.epub_container import EpubItem, TocEntry
from context_aware_translation.documents.epub_support.xml_utils import preserve_outer_whitespace


def normalize_nav_types(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in value.split():
        normalized = token.strip().lower()
        if not normalized:
            continue
        tokens.add(normalized.rsplit(":", 1)[-1])
    return tokens


def walk_nav_label_list(list_el: _ET.Element, *, xhtml_ns: str) -> list[_ET.Element]:
    labels: list[_ET.Element] = []
    for li in list_el.findall(f"./{{{xhtml_ns}}}li"):
        target = li.find(f"./{{{xhtml_ns}}}a")
        if target is None:
            target = li.find(f"./{{{xhtml_ns}}}span")
        if target is None:
            target = li.find(f".//{{{xhtml_ns}}}a")
        if target is None:
            target = li.find(f".//{{{xhtml_ns}}}span")
        if target is not None:
            labels.append(target)

        for child_list in [*li.findall(f"./{{{xhtml_ns}}}ol"), *li.findall(f"./{{{xhtml_ns}}}ul")]:
            labels.extend(walk_nav_label_list(child_list, xhtml_ns=xhtml_ns))
    return labels


def iter_nav_label_targets(nav_el: _ET.Element, *, xhtml_ns: str) -> list[_ET.Element]:
    labels: list[_ET.Element] = []
    for list_el in [*nav_el.findall(f"./{{{xhtml_ns}}}ol"), *nav_el.findall(f"./{{{xhtml_ns}}}ul")]:
        labels.extend(walk_nav_label_list(list_el, xhtml_ns=xhtml_ns))
    return labels


def iter_text_slots(elem: _ET.Element) -> list[tuple[_ET.Element, bool, str]]:
    slots: list[tuple[_ET.Element, bool, str]] = []
    text = elem.text
    if text is not None and text.strip():
        slots.append((elem, False, text))

    for child in elem:
        slots.extend(iter_text_slots(child))
        tail = child.tail
        if tail is not None and tail.strip():
            slots.append((child, True, tail))
    return slots


def set_slot_text(node: _ET.Element, is_tail: bool, value: str) -> None:
    if is_tail:
        node.tail = value
    else:
        node.text = value


def _split_translated_text_across_slots(translated_text: str, slot_texts: list[str]) -> list[str]:
    """Split one translated label string across existing inline text slots."""
    slot_count = len(slot_texts)
    if slot_count == 0:
        return []
    if slot_count == 1:
        return [translated_text]
    if not translated_text:
        return [""] * slot_count

    weights = [max(len(text), 1) for text in slot_texts]
    total_weight = sum(weights)
    text_len = len(translated_text)

    boundaries: list[int] = []
    cumulative_weight = 0
    prev = 0
    for idx, weight in enumerate(weights[:-1], start=1):
        cumulative_weight += weight
        remaining_slots = slot_count - idx
        raw_boundary = round(text_len * cumulative_weight / total_weight)
        min_boundary = prev
        max_boundary = text_len - remaining_slots
        boundary = min(max(raw_boundary, min_boundary), max_boundary)
        if text_len >= slot_count and boundary <= prev:
            boundary = min(prev + 1, max_boundary)
        boundaries.append(boundary)
        prev = boundary

    parts: list[str] = []
    start = 0
    for boundary in boundaries:
        parts.append(translated_text[start:boundary])
        start = boundary
    parts.append(translated_text[start:])
    return parts


def extract_nav_label_specs(
    resources: list[EpubItem],
    *,
    chapter_mime_types: AbstractSet[str],
    nav_translatable_types: set[str],
    xhtml_ns: str,
    epub_ns: str,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for resource in resources:
        media_type = resource.media_type.strip().lower()
        if media_type not in chapter_mime_types:
            continue
        if "nav" not in resource.properties.split():
            continue

        try:
            root = DefusedET.fromstring(resource.content)
        except Exception:
            continue

        for nav_index, nav_el in enumerate(root.iter(f"{{{xhtml_ns}}}nav")):
            nav_type_raw = nav_el.get(f"{{{epub_ns}}}type", "") or nav_el.get("type", "")
            nav_types = normalize_nav_types(nav_type_raw)
            matched_types = sorted(nav_types & nav_translatable_types)
            if not matched_types:
                continue
            nav_type = matched_types[0]

            for label_index, target in enumerate(iter_nav_label_targets(nav_el, xhtml_ns=xhtml_ns)):
                for slot_index, (_node, _is_tail, slot_text) in enumerate(iter_text_slots(target)):
                    specs.append(
                        {
                            "resource_path": resource.file_name,
                            "nav_index": nav_index,
                            "nav_type": nav_type,
                            "label_index": label_index,
                            "slot_index": slot_index,
                            "text": slot_text,
                        }
                    )
    return specs


def deserialize_nav_label_specs(entries: Any, *, nav_translatable_types: set[str]) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    specs: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue

        resource_path = str(entry.get("resource_path", "")).strip()
        if not resource_path:
            continue

        try:
            nav_index = int(entry.get("nav_index", -1))
            label_index = int(entry.get("label_index", -1))
            slot_index = int(entry.get("slot_index", -1))
        except (TypeError, ValueError):
            continue
        if nav_index < 0 or label_index < 0 or slot_index < 0:
            continue

        nav_type = str(entry.get("nav_type", "")).strip().lower()
        if nav_type and nav_type not in nav_translatable_types:
            continue

        specs.append(
            {
                "resource_path": resource_path,
                "nav_index": nav_index,
                "nav_type": nav_type,
                "label_index": label_index,
                "slot_index": slot_index,
                "text": text,
            }
        )
    return specs


def apply_nav_label_specs_to_document(content: bytes, specs: list[dict[str, Any]], *, xhtml_ns: str) -> bytes | None:
    if not specs:
        return None

    try:
        root = DefusedET.fromstring(content)
    except Exception:
        return None

    by_locator: dict[tuple[int, int, int], str] = {}
    for spec in specs:
        try:
            key = (int(spec["nav_index"]), int(spec["label_index"]), int(spec["slot_index"]))
        except Exception:
            continue
        text = spec.get("text")
        if not isinstance(text, str):
            continue
        by_locator[key] = text

    if not by_locator:
        return None

    changed = False
    for nav_index, nav_el in enumerate(root.iter(f"{{{xhtml_ns}}}nav")):
        for label_index, target in enumerate(iter_nav_label_targets(nav_el, xhtml_ns=xhtml_ns)):
            for slot_index, (node, is_tail, slot_text) in enumerate(iter_text_slots(target)):
                key = (nav_index, label_index, slot_index)
                if key not in by_locator:
                    continue
                translated = preserve_outer_whitespace(slot_text, by_locator[key])
                if translated != slot_text:
                    set_slot_text(node, is_tail, translated)
                    changed = True

    if not changed:
        return None
    return bytes(_ET.tostring(root, encoding="utf-8", xml_declaration=True))


def replace_element_text_preserving_slots(elem: _ET.Element, translated_text: str) -> bool:
    """Replace element text while preserving existing inline slot structure."""
    slots = iter_text_slots(elem)
    if not slots:
        if (elem.text or "") != translated_text:
            elem.text = translated_text
            return True
        return False

    slot_texts = [slot_text for _node, _is_tail, slot_text in slots]
    translated_parts = _split_translated_text_across_slots(translated_text, slot_texts)
    changed = False
    for (node, is_tail, slot_text), part in zip(slots, translated_parts, strict=True):
        replacement = preserve_outer_whitespace(slot_text, part)
        current = node.tail if is_tail else node.text
        if current != replacement:
            set_slot_text(node, is_tail, replacement)
            changed = True
    return changed


def sync_nav_ol_with_toc(ol_el: _ET.Element, entries: list[TocEntry], *, xhtml_ns: str) -> bool:
    changed = False
    li_nodes = ol_el.findall(f"{{{xhtml_ns}}}li")
    for li, entry in zip(li_nodes, entries, strict=False):
        a_el = li.find(f"{{{xhtml_ns}}}a")
        span_el = li.find(f"{{{xhtml_ns}}}span")
        target_el = a_el if a_el is not None else span_el
        if target_el is not None:
            changed = replace_element_text_preserving_slots(target_el, entry.title) or changed

        child_ol = li.find(f"{{{xhtml_ns}}}ol")
        if entry.children and child_ol is not None:
            changed = sync_nav_ol_with_toc(child_ol, entry.children, xhtml_ns=xhtml_ns) or changed
    return changed


def update_nav_document(content: bytes, toc: list[TocEntry], *, xhtml_ns: str, epub_ns: str) -> bytes | None:
    try:
        root = DefusedET.fromstring(content)
    except Exception:
        return None

    changed = False
    for nav_el in root.iter(f"{{{xhtml_ns}}}nav"):
        epub_type = nav_el.get(f"{{{epub_ns}}}type", "") or nav_el.get("type", "")
        if "toc" not in normalize_nav_types(epub_type):
            continue
        ol = nav_el.find(f"{{{xhtml_ns}}}ol")
        if ol is None:
            continue
        changed = sync_nav_ol_with_toc(ol, toc, xhtml_ns=xhtml_ns) or changed
        break

    if not changed:
        return None
    return bytes(_ET.tostring(root, encoding="utf-8", xml_declaration=True))


def sync_ncx_navpoints(parent: _ET.Element, entries: list[TocEntry], *, ncx_ns: str) -> bool:
    changed = False
    nav_points = parent.findall(f"{{{ncx_ns}}}navPoint")
    for nav_point, entry in zip(nav_points, entries, strict=False):
        label_el = nav_point.find(f"{{{ncx_ns}}}navLabel/{{{ncx_ns}}}text")
        if label_el is not None:
            changed = replace_element_text_preserving_slots(label_el, entry.title) or changed

        if entry.children:
            changed = sync_ncx_navpoints(nav_point, entry.children, ncx_ns=ncx_ns) or changed
    return changed


def update_ncx_document(content: bytes, toc: list[TocEntry], *, ncx_ns: str) -> bytes | None:
    try:
        root = DefusedET.fromstring(content)
    except Exception:
        return None

    nav_map = root.find(f"{{{ncx_ns}}}navMap")
    if nav_map is None:
        return None

    changed = sync_ncx_navpoints(nav_map, toc, ncx_ns=ncx_ns)
    if not changed:
        return None
    return bytes(_ET.tostring(root, encoding="utf-8", xml_declaration=True))


def apply_translated_toc_to_resources(
    resources: list[EpubItem],
    toc: list[TocEntry],
    *,
    chapter_mime_types: AbstractSet[str],
    xhtml_ns: str,
    epub_ns: str,
    ncx_ns: str,
) -> None:
    """Update nav/ncx resource payloads so translated TOC titles are reflected in output."""
    for item in resources:
        media_type = item.media_type.strip().lower()
        if media_type in chapter_mime_types:
            updated = update_nav_document(item.content, toc, xhtml_ns=xhtml_ns, epub_ns=epub_ns)
            if updated is not None:
                item.content = updated
        elif media_type == "application/x-dtbncx+xml":
            updated = update_ncx_document(item.content, toc, ncx_ns=ncx_ns)
            if updated is not None:
                item.content = updated
