"""Tests for EPUB XHTML text extraction and injection utilities."""

from __future__ import annotations

import pytest

from context_aware_translation.documents.epub_xhtml_utils import (
    extract_heading_texts,
    extract_text_from_xhtml,
    flatten_annotationless_ruby_in_xhtml,
    inject_translations_into_xhtml,
)
from context_aware_translation.utils.compression_marker import COMPRESSED_LINE_SENTINEL


class TestExtractTextFromXhtml:
    def test_extract_text_paragraphs(self):
        xhtml = "<html><body><p>Hello world</p><p>Second paragraph</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Hello world", "Second paragraph"]

    def test_extract_text_headings(self):
        xhtml = "<html><body><h1>Title</h1><h2>Subtitle</h2><h3>Section</h3></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Title", "Subtitle", "Section"]

    def test_extract_text_lists(self):
        xhtml = "<html><body><ul><li>Item 1</li><li>Item 2</li></ul></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Item 1", "Item 2"]

    def test_extract_text_nested_inline(self):
        xhtml = "<html><body><p>This is <em>italic</em> and <strong>bold</strong> text.</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["This is ⟪em:0⟫italic⟪/em:0⟫ and ⟪strong:1⟫bold⟪/strong:1⟫ text."]

    def test_extract_text_empty_elements(self):
        xhtml = "<html><body><p></p><p>Not empty</p><p>   </p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Not empty"]

    def test_extract_text_xhtml_namespace(self):
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            "<head><title>Test</title></head>"
            "<body><p>Namespaced paragraph</p></body>"
            "</html>"
        )
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Test", "Namespaced paragraph"]

    def test_extract_text_includes_translatable_attributes(self):
        xhtml = '<html><body><p>Read <img src="cover.jpg" alt="Cover image" title="Front"/> now.</p></body></html>'
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Read ⟪img:0⟫⟪/img:0⟫ now.", "Cover image", "Front"]

    def test_extract_text_includes_attributes_on_non_leaf_blocks(self):
        xhtml = '<html><body><section title="Container title"><p>Inside paragraph</p></section></body></html>'
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Container title", "Inside paragraph"]

    def test_extract_text_includes_standalone_attributes_outside_blocks(self):
        xhtml = '<html><body><img src="cover.jpg" alt="Cover image" title="Front cover"/></body></html>'
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Cover image", "Front cover"]

    def test_extract_text_includes_nested_block_text_under_non_block_wrapper(self):
        xhtml = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
            "<section><p>Paragraph text</p><svg xmlns='http://www.w3.org/2000/svg'><text>Vector label</text></svg></section>"
            "</body></html>"
        )
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Paragraph text", "Vector label"]

    def test_extract_text_xml_declaration(self):
        xhtml = '<?xml version="1.0" encoding="utf-8"?><html><body><p>With declaration</p></body></html>'
        result = extract_text_from_xhtml(xhtml)
        assert result == ["With declaration"]

    def test_extract_text_self_closing_tags(self):
        xhtml = "<html><body><p>Before<br/>After</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Before⟪BR:0⟫After"]

    def test_extract_text_nested_divs(self):
        """Div containing p children: only p text extracted (no double-count)."""
        xhtml = "<html><body><div><p>Inside div</p><p>Also inside</p></div></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Inside div", "Also inside"]

    def test_extract_text_div_with_direct_text(self):
        """Div with no child blocks: text extracted directly."""
        xhtml = "<html><body><div>Direct text in div</div></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Direct text in div"]

    def test_extract_text_blockquote(self):
        xhtml = "<html><body><blockquote>Quoted text</blockquote></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Quoted text"]

    def test_extract_text_table_cells(self):
        xhtml = "<html><body><table><tr><td>Cell 1</td><td>Cell 2</td></tr></table></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Cell 1", "Cell 2"]

    def test_extract_text_definition_list(self):
        xhtml = "<html><body><dl><dt>Term</dt><dd>Definition</dd></dl></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Term", "Definition"]

    def test_extract_text_mixed_content(self):
        xhtml = (
            "<html><body>"
            "<h1>Title</h1>"
            "<p>Paragraph with <a href='#'>link</a>.</p>"
            "<ul><li>List item</li></ul>"
            "</body></html>"
        )
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Title", "Paragraph with ⟪a:0⟫link⟪/a:0⟫.", "List item"]

    def test_extract_text_toc_like_single_anchor_line_stays_plain(self):
        xhtml = "<html><body><li><a href='ch1.xhtml'>過去はいつだって背後から刺して来る</a></li></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["過去はいつだって背後から刺して来る"]

    def test_extract_text_single_wrapper_chain_stays_plain(self):
        xhtml = "<html><body><li><a href='ch1.xhtml'><span>Nested label</span></a></li></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Nested label"]

    def test_extract_text_deeply_nested_inline(self):
        xhtml = "<html><body><p><span><em><strong>Deep</strong></em></span> text</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["⟪span:0⟫⟪em:0/0⟫⟪strong:0/0/0⟫Deep⟪/strong:0/0/0⟫⟪/em:0/0⟫⟪/span:0⟫ text"]

    def test_extract_text_whitespace_handling(self):
        xhtml = "<html><body><p>  Leading and trailing  </p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["  Leading and trailing  "]

    def test_extract_text_preformatted_block(self):
        xhtml = "<html><body><pre>line one\nline two</pre></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["line one\nline two"]

    def test_extract_text_svg_text_nodes(self):
        xhtml = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
            '<svg xmlns="http://www.w3.org/2000/svg"><text>Vector label</text></svg>'
            "</body></html>"
        )
        result = extract_text_from_xhtml(xhtml)
        assert result == ["Vector label"]


class TestExtractHeadingTexts:
    def test_extract_heading_simple(self):
        xhtml = "<html><body><h1>Chapter One</h1><p>Content</p></body></html>"
        assert extract_heading_texts(xhtml) == ["Chapter One"]

    def test_extract_heading_multiple_levels(self):
        xhtml = "<html><body><h1>Part 1</h1><h2>Chapter 1</h2><p>Text</p><h2>Chapter 2</h2></body></html>"
        assert extract_heading_texts(xhtml) == ["Part 1", "Chapter 1", "Chapter 2"]

    def test_extract_heading_with_inline_children(self):
        xhtml = "<html><body><h1>Chapter <em>One</em></h1></body></html>"
        assert extract_heading_texts(xhtml) == ["Chapter One"]

    def test_extract_heading_empty_preserved(self):
        xhtml = "<html><body><h1></h1><h2>Real Title</h2></body></html>"
        result = extract_heading_texts(xhtml)
        assert result == ["", "Real Title"]

    def test_extract_heading_xhtml_namespace(self):
        xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Title</h1><h2>Sub</h2></body></html>'
        assert extract_heading_texts(xhtml) == ["Title", "Sub"]

    def test_extract_heading_none(self):
        xhtml = "<html><body><p>No headings here</p></body></html>"
        assert extract_heading_texts(xhtml) == []


class TestFlattenAnnotationlessRuby:
    def test_flatten_annotationless_ruby_preserves_inline_children(self):
        xhtml = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>'
            '<ruby><rb><a href="https://example.com"><em>Important</em></a></rb><rt></rt></ruby>'
            " tail"
            "</p></body></html>"
        )

        result = flatten_annotationless_ruby_in_xhtml(xhtml)

        assert "<ruby" not in result
        assert "<rt" not in result
        assert '<a href="https://example.com"><em>Important</em></a>' in result


class TestInjectTranslationsIntoXhtml:
    def test_inject_translations_basic(self):
        xhtml = "<html><body><p>Hello</p><p>World</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Hola", "Mundo"])
        assert consumed == 2
        assert "Hola" in result
        assert "Mundo" in result

    def test_inject_translations_preserves_structure(self):
        xhtml = '<html><body><div class="chapter"><p>Text</p></div></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["Translated"])
        assert consumed == 1
        assert 'class="chapter"' in result
        assert "Translated" in result

    def test_inject_translations_round_trip(self):
        xhtml = "<html><body><p>Original text</p><p>Another paragraph</p></body></html>"
        texts = extract_text_from_xhtml(xhtml)
        result, consumed = inject_translations_into_xhtml(xhtml, texts)
        assert consumed == 2
        re_extracted = extract_text_from_xhtml(result)
        assert re_extracted == texts

    def test_inject_translations_count(self):
        xhtml = "<html><body><h1>Title</h1><p>Para 1</p><p>Para 2</p></body></html>"
        _, consumed = inject_translations_into_xhtml(xhtml, ["T", "P1", "P2"])
        assert consumed == 3

    def test_inject_preserves_literal_unknown_marker_in_attribute_text(self):
        xhtml = '<html><body><img src="c.jpg" alt="old alt"/></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["Keep ⟪NOT A MARKER⟫ text"])
        assert consumed == 1
        assert extract_text_from_xhtml(result) == ["Keep ⟪NOT A MARKER⟫ text"]

    def test_inject_preserves_xml_declaration(self):
        xhtml = '<?xml version="1.0" encoding="utf-8"?><html><body><p>Text</p></body></html>'
        result, _ = inject_translations_into_xhtml(xhtml, ["Translated"])
        assert result.startswith('<?xml version="1.0" encoding="utf-8"?>')

    def test_inject_normalizes_non_utf8_xml_declaration(self):
        xhtml = '<?xml version="1.0" encoding="iso-8859-1"?><html><body><p>café</p></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["café"])
        assert consumed == 1
        assert result.startswith('<?xml version="1.0" encoding="utf-8"?>')
        assert "café" in result

    def test_inject_fewer_translations_than_blocks(self):
        xhtml = "<html><body><p>First</p><p>Second</p><p>Third</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Only one"])
        assert consumed == 1
        assert "Only one" in result

    def test_inject_with_offset(self):
        xhtml = "<html><body><p>Text</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Skip", "Use this"], offset=1)
        assert consumed == 1
        assert "Use this" in result

    def test_inject_preserves_inline_formatting(self):
        xhtml = "<html><body><p>This is <em>italic</em> text</p></body></html>"
        translations = ["Esto es ⟪em:0⟫cursiva⟪/em:0⟫ texto"]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == len(translations)
        assert "<em>" in result
        assert extract_text_from_xhtml(result) == ["Esto es ⟪em:0⟫cursiva⟪/em:0⟫ texto"]

    def test_inject_preserves_link_elements(self):
        xhtml = '<html><body><p>Read <a href="https://example.com">here</a> now.</p></body></html>'
        translations = ["Lea ⟪a:0⟫aqui⟪/a:0⟫ ahora."]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == len(translations)
        assert '<a href="https://example.com">' in result
        assert extract_text_from_xhtml(result) == ["Lea ⟪a:0⟫aqui⟪/a:0⟫ ahora."]

    def test_inject_toc_like_single_anchor_line_without_tokens(self):
        xhtml = "<html><body><li><a href='ch1.xhtml'>過去はいつだって背後から刺して来る</a></li></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["The past always stabs from behind."])
        assert consumed == 1
        assert 'href="ch1.xhtml"' in result
        assert extract_text_from_xhtml(result) == ["The past always stabs from behind."]

    def test_inject_single_wrapper_chain_without_tokens(self):
        xhtml = "<html><body><li><a href='ch1.xhtml'><span>Nested label</span></a></li></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Translated nested label"])
        assert consumed == 1
        assert 'href="ch1.xhtml"' in result
        assert extract_text_from_xhtml(result) == ["Translated nested label"]

    def test_inject_translates_title_and_attributes(self):
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<html><head><title>Chapter One</title></head>"
            "<body>"
            '<p>Read <img src="cover.jpg" alt="Cover image" aria-label="Cover"/> now.</p>'
            "</body></html>"
        )
        translations = [
            "Capitulo Uno",
            "Lea ⟪img:0⟫⟪/img:0⟫ ahora.",
            "Imagen de portada",
            "Portada",
        ]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == len(translations)
        assert "<title>Capitulo Uno</title>" in result
        assert 'alt="Imagen de portada"' in result
        assert 'aria-label="Portada"' in result
        assert extract_text_from_xhtml(result) == [
            "Capitulo Uno",
            "Lea ⟪img:0⟫⟪/img:0⟫ ahora.",
            "Imagen de portada",
            "Portada",
        ]

    def test_inject_translates_attributes_on_non_leaf_blocks(self):
        xhtml = '<html><body><section title="Container title"><p>Inside paragraph</p></section></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["Titulo del contenedor", "Parrafo interno"])
        assert consumed == 2
        assert 'title="Titulo del contenedor"' in result
        assert extract_text_from_xhtml(result) == ["Titulo del contenedor", "Parrafo interno"]

    def test_inject_translates_standalone_attributes_outside_blocks(self):
        xhtml = '<html><body><img src="cover.jpg" alt="Cover image" title="Front cover"/></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["Imagen de portada", "Portada"])
        assert consumed == 2
        assert 'alt="Imagen de portada"' in result
        assert 'title="Portada"' in result
        assert extract_text_from_xhtml(result) == ["Imagen de portada", "Portada"]

    def test_inject_into_nested_divs(self):
        xhtml = "<html><body><div><p>Inner</p></div></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Translated inner"])
        assert consumed == 1
        assert "Translated inner" in result

    def test_inject_xhtml_namespace(self):
        xhtml = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Original</p></body></html>'
        result, consumed = inject_translations_into_xhtml(xhtml, ["Translated"])
        assert consumed == 1
        assert "Translated" in result
        assert "ns0:" not in result

    def test_extract_inject_worked_example(self):
        """Implements the worked example from plan Section 4.3."""
        xhtml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            "<head><title>Chapter 1</title></head>"
            "<body>"
            "<h1>The Beginning</h1>"
            "<p>It was a <em>dark</em> and stormy night.</p>"
            "<p>The wind howled through the trees.</p>"
            "<div>"
            "<p>She opened the door.</p>"
            "<p>Nobody was there.</p>"
            "</div>"
            "</body>"
            "</html>"
        )

        # Step 1: Extract
        texts = extract_text_from_xhtml(xhtml)
        assert texts == [
            "Chapter 1",
            "The Beginning",
            "It was a ⟪em:0⟫dark⟪/em:0⟫ and stormy night.",
            "The wind howled through the trees.",
            "She opened the door.",
            "Nobody was there.",
        ]

        # Step 2: Inject translations
        translations = [
            "Capitulo 1",
            "El Comienzo",
            "Era una ⟪em:0⟫noche oscura⟪/em:0⟫ y tormentosa.",
            "El viento aullaba entre los arboles.",
            "Ella abrio la puerta.",
            "No habia nadie.",
        ]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == len(translations)

        # Step 3: Verify translations injected
        re_extracted = extract_text_from_xhtml(result)
        assert re_extracted == [
            "Capitulo 1",
            "El Comienzo",
            "Era una ⟪em:0⟫noche oscura⟪/em:0⟫ y tormentosa.",
            "El viento aullaba entre los arboles.",
            "Ella abrio la puerta.",
            "No habia nadie.",
        ]

        # Step 4: Verify XML declaration preserved
        assert '<?xml version="1.0" encoding="utf-8"?>' in result


class TestRubyHandling:
    """Tests for <ruby>/<rt> annotation merging and round-tripping."""

    def test_extract_ruby_merges_base_and_rt(self):
        xhtml = "<html><body><p>The word <ruby>泥掘り<rt>マッドディグ</rt></ruby> is a name.</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["The word ⟪RUBY:0⟫泥掘り(マッドディグ)⟪/RUBY:0⟫ is a name."]

    def test_extract_ruby_with_rp_elements(self):
        xhtml = "<html><body><p><ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>text</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫text"]

    def test_extract_ruby_no_rt(self):
        """<ruby> with no <rt> child should just yield base text."""
        xhtml = "<html><body><p><ruby>plain</ruby> after</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["⟪RUBY:0⟫plain⟪/RUBY:0⟫ after"]

    def test_extract_ruby_with_rb_element(self):
        """<ruby><rb>base</rb><rt>reading</rt></ruby> variant."""
        xhtml = "<html><body><p><ruby><rb>泥掘り</rb><rt>マッドディグ</rt></ruby>がいる</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        assert result == ["⟪RUBY:0⟫泥掘り(マッドディグ)⟪/RUBY:0⟫がいる"]

    def test_extract_ruby_multiple_in_paragraph(self):
        xhtml = (
            "<html><body><p>"
            "<ruby>薪枝<rt>たきぎえだ</rt></ruby>と"
            "<ruby>泥掘り<rt>マッドディグ</rt></ruby>がいる"
            "</p></body></html>"
        )
        result = extract_text_from_xhtml(xhtml)
        assert result == ["⟪RUBY:0⟫薪枝(たきぎえだ)⟪/RUBY:0⟫と⟪RUBY:1⟫泥掘り(マッドディグ)⟪/RUBY:1⟫がいる"]

    def test_inject_ruby_splits_back(self):
        xhtml = "<html><body><p>Word <ruby>泥掘り<rt>マッドディグ</rt></ruby> here.</p></body></html>"
        translations = ["单词 ⟪RUBY:0⟫泥掘(Mud Dig)⟪/RUBY:0⟫ 在这里。"]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == 1
        re_extracted = extract_text_from_xhtml(result)
        assert re_extracted == ["单词 ⟪RUBY:0⟫泥掘(Mud Dig)⟪/RUBY:0⟫ 在这里。"]

    def test_inject_ruby_with_rb_updates_base_and_rt(self):
        xhtml = (
            "<html><body><p>"
            "一边流览着伴随着异常宏大的乐曲播放的"
            "<ruby><rb>戦犯リスト</rb><rt>キャストロール</rt></ruby>"
            "，嘴上虽然这么说着。"
            "</p></body></html>"
        )
        translations = ["一边流览着伴随着异常宏大的乐曲播放的⟪RUBY:0⟫战犯名单(演职员表)⟪/RUBY:0⟫，嘴上虽然这么说着。"]
        result, consumed = inject_translations_into_xhtml(xhtml, translations)
        assert consumed == 1
        assert "<rb>战犯名单</rb>" in result
        assert "<rt>演职员表</rt>" in result
        assert "戦犯リスト" not in result
        assert "キャストロール" not in result
        assert extract_text_from_xhtml(result) == translations

    def test_inject_ruby_splits_fullwidth_parentheses_into_rt(self):
        xhtml = "<html><body><p>Word <ruby>泥掘り<rt>マッドディグ</rt></ruby> here.</p></body></html>"
        translation = ["Word ⟪RUBY:0⟫战犯名单（演职员表）⟪/RUBY:0⟫ here."]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert "<ruby>战犯名单<rt>演职员表</rt></ruby>" in result
        re_extracted = extract_text_from_xhtml(result)
        assert re_extracted == ["Word ⟪RUBY:0⟫战犯名单(演职员表)⟪/RUBY:0⟫ here."]

    def test_inject_ruby_no_parens_clears_rt(self):
        """When translated text has no parenthetical, <rt> is cleared."""
        xhtml = "<html><body><p><ruby>泥掘り<rt>マッドディグ</rt></ruby></p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["⟪RUBY:0⟫泥掘⟪/RUBY:0⟫"])
        assert consumed == 1
        re_extracted = extract_text_from_xhtml(result)
        assert re_extracted == ["泥掘"]

    def test_extract_ruby_can_strip_annotations_from_translation_slots(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        result = extract_text_from_xhtml(xhtml, strip_ruby_annotations=True)
        assert result == ["Before ⟪RUBY:0⟫漢字⟪/RUBY:0⟫ after"]

    def test_inject_strip_ruby_annotations_ignores_translated_rt_text(self):
        xhtml = "<html><body><p><ruby>女主角<rt>ヒロイン</rt></ruby></p></body></html>"
        result, consumed = inject_translations_into_xhtml(
            xhtml,
            ["女主角(臭婊子)"],
            strip_ruby_annotations=True,
        )
        assert consumed == 1
        assert "臭婊子" not in result
        assert "ヒロイン" not in result
        assert extract_text_from_xhtml(result, strip_ruby_annotations=True) == ["女主角"]

    def test_inject_ruby_no_parens_clears_rp_fallback_text(self):
        xhtml = (
            "<html><body><p>"
            "<ruby>断罪飛び蹴り<rp>⟪</rp><rt>パニッシュメントドロップ</rt><rp>⟫</rp></ruby>"
            "</p></body></html>"
        )
        result, consumed = inject_translations_into_xhtml(xhtml, ["⟪RUBY:0⟫断罪飞踢⟪/RUBY:0⟫"])
        assert consumed == 1
        assert "⟪</rp>" not in result
        assert "⟫</rp>" not in result
        assert extract_text_from_xhtml(result) == ["断罪飞踢"]

    def test_inject_ruby_no_parens_clears_ascii_parentheses_rp_fallback(self):
        xhtml = (
            "<html><body><p>"
            "<ruby>断罪飛び蹴り<rp>(</rp><rt>パニッシュメントドロップ</rt><rp>)</rp></ruby>"
            "</p></body></html>"
        )
        result, consumed = inject_translations_into_xhtml(xhtml, ["⟪RUBY:0⟫断罪飞踢⟪/RUBY:0⟫"])
        assert consumed == 1
        assert "(</rp>" not in result
        assert ")</rp>" not in result
        assert extract_text_from_xhtml(result) == ["断罪飞踢"]

    def test_inject_ruby_with_annotation_clears_rp_fallback_text(self):
        xhtml = "<html><body><p><ruby>女主角<rp>《</rp><rt>ヒロイン</rt><rp>》</rp></ruby></p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["⟪RUBY:0⟫女主角(臭婊子)⟪/RUBY:0⟫"])
        assert consumed == 1
        assert "<rt>臭婊子</rt>" in result
        assert "《</rp>" not in result
        assert "》</rp>" not in result
        assert extract_text_from_xhtml(result) == ["女主角(臭婊子)"]

    def test_inject_ruby_removes_stale_rtc_annotations(self):
        xhtml = (
            "<html><body><p>"
            "<ruby>使い捨て魔術媒体<rt>マジックスクロール</rt><rtc><rt>マジックスクロール</rt></rtc></ruby>"
            "</p></body></html>"
        )
        result, consumed = inject_translations_into_xhtml(
            xhtml,
            ["⟪RUBY:0⟫一次性魔术媒介（魔法卷轴）⟪/RUBY:0⟫"],
        )
        assert consumed == 1
        assert "<rtc>" not in result
        assert "<rt>魔法卷轴</rt>" in result
        assert "マジックスクロール" not in result

    def test_inject_ruby_no_parens_removes_rtc_annotations(self):
        xhtml = (
            "<html><body><p>"
            "<ruby>使い捨て魔術媒体<rt>マジックスクロール</rt><rtc><rt>マジックスクロール</rt></rtc></ruby>"
            "</p></body></html>"
        )
        result, consumed = inject_translations_into_xhtml(
            xhtml,
            ["⟪RUBY:0⟫一次性魔术媒介⟪/RUBY:0⟫"],
        )
        assert consumed == 1
        assert "<rtc>" not in result
        assert "マジックスクロール" not in result

    def test_inject_ruby_empty_parentheses_collapse_to_base_text(self):
        xhtml = "<html><body><p><ruby>女主角<rp>(</rp><rt>ヒロイン</rt><rp>)</rp></ruby></p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["⟪RUBY:0⟫女主角()⟪/RUBY:0⟫"])
        assert consumed == 1
        assert "女主角()" not in result
        assert extract_text_from_xhtml(result) == ["女主角"]

    @pytest.mark.parametrize(
        "suffix",
        ["（）", "（  ）", "《》", "「」", "【 】", "[]", "{}", "〔 〕", "〖〗", "⟪ ⟫"],
    )
    def test_inject_ruby_empty_bracket_shells_collapse_to_base_text(self, suffix: str):
        xhtml = "<html><body><p><ruby>女主角<rp>(</rp><rt>ヒロイン</rt><rp>)</rp></ruby></p></body></html>"
        result, consumed = inject_translations_into_xhtml(
            xhtml,
            [f"⟪RUBY:0⟫女主角{suffix}⟪/RUBY:0⟫"],
        )
        assert consumed == 1
        assert extract_text_from_xhtml(result) == ["女主角"]

    def test_ruby_round_trip(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        texts = extract_text_from_xhtml(xhtml)
        assert texts == ["Before ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ after"]
        result, consumed = inject_translations_into_xhtml(xhtml, texts)
        assert consumed == 1
        assert extract_text_from_xhtml(result) == texts

    def test_ruby_reduces_slot_count(self):
        """Ruby merging should produce fewer slots than treating base+rt separately."""
        xhtml = "<html><body><p>She said <ruby>泥掘り<rt>マッドディグ</rt></ruby> is coming.</p></body></html>"
        result = extract_text_from_xhtml(xhtml)
        # Merged-inline mode keeps ruby in a single tokenized slot.
        assert len(result) == 1


class TestMergedInlineValidation:
    def test_inject_falls_back_when_inline_tokens_removed(self):
        xhtml = "<html><body><p>This is <em>italic</em> text</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Texto sin tokens"])
        assert consumed == 1
        assert extract_text_from_xhtml(result) == ["Texto sin tokens"]

    def test_inject_allows_empty_compressed_line_for_strict_inline_blocks(self):
        xhtml = "<html><body><p>This is <em>italic</em> and <strong>bold</strong> text</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, [""])
        assert consumed == 1
        assert "<em" not in result
        assert "<strong" not in result
        assert extract_text_from_xhtml(result) == []

    def test_inject_allows_sentinel_compressed_line_for_strict_inline_blocks(self):
        xhtml = "<html><body><p>This is <em>italic</em> and <strong>bold</strong> text</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, [COMPRESSED_LINE_SENTINEL])
        assert consumed == 1
        assert "<em" not in result
        assert "<strong" not in result
        assert extract_text_from_xhtml(result) == []

    def test_inject_compressed_line_keeps_strict_img_node(self):
        xhtml = "<html><body><p>Before <img src='x.jpg' alt='Cover'/> after</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, [""])
        assert consumed == 1
        assert '<img src="x.jpg"' in result
        assert extract_text_from_xhtml(result) == ["Cover"]

    def test_inject_allows_missing_ruby_tokens(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Before 漢字 after"])
        assert consumed == 1
        assert "<ruby>" not in result
        assert extract_text_from_xhtml(result) == ["Before 漢字 after"]

    def test_inject_allows_missing_br_tokens(self):
        xhtml = "<html><body><p>Before<br/>After</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Before After"])
        assert consumed == 1
        assert "<br" not in result
        assert extract_text_from_xhtml(result) == ["Before After"]

    def test_inject_mixed_inline_missing_ruby_drops_ruby_keeps_strict_inline(self):
        xhtml = "<html><body><p>A <em>Before <ruby>漢字<rt>かんじ</rt></ruby> After</em> Z</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["A ⟪em:0⟫中間テキスト⟪/em:0⟫ Z"])
        assert consumed == 1
        assert "<em>" in result
        assert "<ruby" not in result
        assert extract_text_from_xhtml(result) == ["A ⟪em:0⟫中間テキスト⟪/em:0⟫ Z"]

    def test_inject_mixed_inline_missing_br_drops_br_keeps_strict_inline(self):
        xhtml = "<html><body><p>A <em>Left<br/>Right</em> Z</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["A ⟪em:0⟫左右⟪/em:0⟫ Z"])
        assert consumed == 1
        assert "<em>" in result
        assert "<br" not in result
        assert extract_text_from_xhtml(result) == ["A ⟪em:0⟫左右⟪/em:0⟫ Z"]

    def test_inject_two_ruby_one_missing_preserves_other_ruby(self):
        xhtml = "<html><body><p>A <ruby>一<rt>いち</rt></ruby> B <ruby>二<rt>に</rt></ruby> C</p></body></html>"
        translation = ["A 一 B ⟪RUBY:1⟫二(er)⟪/RUBY:1⟫ C"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert result.count("<ruby>") == 1
        re_extracted = extract_text_from_xhtml(result)
        assert len(re_extracted) == 1
        assert "⟪RUBY:0⟫二(er)⟪/RUBY:0⟫" in re_extracted[0]
        assert "一(" not in re_extracted[0]

    def test_inject_falls_back_on_unclosed_ruby_marker(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Before ⟪RUBY:0⟫漢字 after"])
        assert consumed == 1
        assert extract_text_from_xhtml(result) == ["Before 漢字 after"]

    def test_inject_falls_back_on_unopened_ruby_marker(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Before 漢字⟪/RUBY:0⟫ after"])
        assert consumed == 1
        assert extract_text_from_xhtml(result) == ["Before 漢字 after"]

    def test_inject_source_truth_drops_metadata_wrapper_but_keeps_style_wrapper(self):
        xhtml = "<html><body><p>Plain</p></body></html>"
        translation = ["A ⟪a:0⟫link⟪/a:0⟫ and ⟪strong:1⟫bold⟪/strong:1⟫"]
        result, consumed = inject_translations_into_xhtml(xhtml, [translation[0]])
        assert consumed == 1
        assert "<a" not in result
        assert "<strong>bold</strong>" in result
        re_extracted = extract_text_from_xhtml(result)
        assert len(re_extracted) == 1
        assert "link" in re_extracted[0]
        assert "⟪strong:0⟫bold⟪/strong:0⟫" in re_extracted[0]

    def test_inject_source_truth_infers_ruby_without_original_metadata(self):
        xhtml = "<html><body><p>Plain</p></body></html>"
        translation = ["A ⟪RUBY:0⟫漢字(かんじ)⟪/RUBY:0⟫ B"]
        result, consumed = inject_translations_into_xhtml(xhtml, [translation[0]])
        assert consumed == 1
        assert "<ruby>漢字<rt>かんじ</rt></ruby>" in result
        assert extract_text_from_xhtml(result) == translation

    def test_merged_inline_fallback_rebuilds_from_source_truth_markers(self):
        xhtml = "<html><body><p>This is <em>italic</em> text</p></body></html>"
        # strict token/path mismatch triggers merged-inline fallback branch
        translation = ["X ⟪a:9⟫Y⟪/a:9⟫ ⟪strong:2⟫Z⟪/strong:2⟫"]
        result, consumed = inject_translations_into_xhtml(xhtml, [translation[0]])
        assert consumed == 1
        assert "<strong>Z</strong>" in result
        assert "<a" not in result
        assert "<em>" not in result
        assert extract_text_from_xhtml(result) == ["X Y ⟪strong:0⟫Z⟪/strong:0⟫"]

    def test_merged_inline_fallback_drops_strict_structure_to_plain_text(self):
        xhtml = "<html><body><p>Go <a href='u'>here</a> now.</p></body></html>"
        result, consumed = inject_translations_into_xhtml(xhtml, ["Ir ⟪a:0⟫aqui ahora."])
        assert consumed == 1
        assert "<a " not in result
        assert extract_text_from_xhtml(result) == ["Ir aqui ahora."]

    def test_inject_accepts_fullwidth_delimiters_for_ruby_markers(self):
        xhtml = "<html><body><p>Before <ruby>漢字<rt>かんじ</rt></ruby> after</p></body></html>"
        translation = ["Before 《RUBY:0》汉字(hanzi)《/RUBY:0》 after"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert "《RUBY:" not in result
        assert "《/RUBY:" not in result
        assert extract_text_from_xhtml(result) == ["Before ⟪RUBY:0⟫汉字(hanzi)⟪/RUBY:0⟫ after"]

    def test_inject_accepts_fullwidth_delimiters_for_strict_inline_markers(self):
        xhtml = "<html><body><p>A <em>B</em> C</p></body></html>"
        translation = ["A 《em:0》粗体《/em:0》 C"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert "<em>粗体</em>" in result
        assert extract_text_from_xhtml(result) == ["A ⟪em:0⟫粗体⟪/em:0⟫ C"]

    def test_inject_wrong_ruby_indexes_preserve_ruby_by_occurrence(self):
        xhtml = "<html><body><p>A <ruby>一<rt>いち</rt></ruby> B <ruby>二<rt>に</rt></ruby> C</p></body></html>"
        translation = ["A ⟪RUBY:8⟫one(o)⟪/RUBY:8⟫ B ⟪RUBY:9⟫two(t)⟪/RUBY:9⟫ C"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert result.count("<ruby>") == 2
        assert extract_text_from_xhtml(result) == ["A ⟪RUBY:0⟫one(o)⟪/RUBY:0⟫ B ⟪RUBY:1⟫two(t)⟪/RUBY:1⟫ C"]

    def test_inject_mixed_strict_wrong_ruby_indexes_preserve_ruby_by_occurrence(self):
        xhtml = (
            "<html><body><p>X <em>Y</em> A <ruby>一<rt>いち</rt></ruby> "
            "B <ruby>二<rt>に</rt></ruby> C</p></body></html>"
        )
        translation = ["X ⟪em:0⟫Z⟪/em:0⟫ A ⟪RUBY:8⟫one(o)⟪/RUBY:8⟫ B ⟪RUBY:9⟫two(t)⟪/RUBY:9⟫ C"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert "<em>" in result
        assert result.count("<ruby>") == 2
        assert extract_text_from_xhtml(result) == [
            "X ⟪em:0⟫Z⟪/em:0⟫ A ⟪RUBY:1⟫one(o)⟪/RUBY:1⟫ B ⟪RUBY:2⟫two(t)⟪/RUBY:2⟫ C"
        ]

    def test_inject_extra_ruby_markers_are_safe_and_do_not_create_extra_ruby_nodes(self):
        xhtml = "<html><body><p>A <ruby>一<rt>いち</rt></ruby> C</p></body></html>"
        translation = ["A ⟪RUBY:0⟫one(o)⟪/RUBY:0⟫ ⟪RUBY:9⟫extra(e)⟪/RUBY:9⟫ C"]
        result, consumed = inject_translations_into_xhtml(xhtml, translation)
        assert consumed == 1
        assert result.count("<ruby>") == 1
        assert extract_text_from_xhtml(result) == ["A ⟪RUBY:0⟫one(o)⟪/RUBY:0⟫ extra(e) C"]

    def test_round_trip_escapes_literal_token_delimiters(self):
        xhtml = "<html><body><p>Literal ⟪<em>X</em>⟫ markers</p></body></html>"
        slots = extract_text_from_xhtml(xhtml)
        assert slots == ["Literal \ue000⟪⟪em:0⟫X⟪/em:0⟫\ue000⟫ markers"]
        translated = ["Traducido \ue000⟪⟪em:0⟫Y⟪/em:0⟫\ue000⟫ marcas"]
        result, consumed = inject_translations_into_xhtml(xhtml, translated)
        assert consumed == 1
        assert extract_text_from_xhtml(result) == translated

    def test_nested_unknown_inline_round_trip(self):
        xhtml = "<html><body><p><foo>left <bar>inside</bar></foo> right</p></body></html>"
        slots = extract_text_from_xhtml(xhtml)
        assert slots == ["⟪foo:0⟫left ⟪bar:0/0⟫inside⟪/bar:0/0⟫⟪/foo:0⟫ right"]
        translated = ["⟪foo:0⟫izq ⟪bar:0/0⟫interno⟪/bar:0/0⟫⟪/foo:0⟫ der"]
        result, consumed = inject_translations_into_xhtml(xhtml, translated)
        assert consumed == 1
        assert extract_text_from_xhtml(result) == translated
