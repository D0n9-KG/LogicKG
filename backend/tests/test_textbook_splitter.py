from pathlib import Path

from app.ingest.textbook_splitter import split_textbook_md


def test_split_textbook_prefers_real_chapter_headings_and_drops_watermark(tmp_path: Path) -> None:
    md = tmp_path / "book.md"
    md.write_text(
        "\n".join(
            [
                "# 多相流基础",
                "",
                "# 目录",
                "",
                "# 第1章多相流简介",
                "",
                "# 1.1 引言",
                "多相流是...",
                "# 仅供个人科研教学使用！",
                "这里是页眉水印，不该影响切分。",
                "",
                "# 第 $2$ 章 单个粒子运动",
                "",
                "# 2.1 引言",
                "粒子运动...",
            ]
        ),
        encoding="utf-8",
    )

    chapters = split_textbook_md(str(md))

    assert [chapter.chapter_num for chapter in chapters] == [0, 1, 2]
    assert chapters[0].title == "Preface"
    assert chapters[1].title == "第1章多相流简介"
    assert chapters[2].title == "第 $2$ 章 单个粒子运动"
    assert "# 1.1 引言" in chapters[1].body
    assert "仅供个人科研教学使用" not in chapters[1].body


def test_split_textbook_falls_back_to_generic_headings_when_no_chapter_heading_exists(tmp_path: Path) -> None:
    md = tmp_path / "notes.md"
    md.write_text(
        "\n".join(
            [
                "# 概述",
                "内容A",
                "# 方法",
                "内容B",
            ]
        ),
        encoding="utf-8",
    )

    chapters = split_textbook_md(str(md))

    assert [chapter.title for chapter in chapters] == ["概述", "方法"]


def test_split_textbook_uses_last_chapter_one_after_table_of_contents(tmp_path: Path) -> None:
    md = tmp_path / "toc.md"
    md.write_text(
        "\n".join(
            [
                "# 目录",
                "# 第1章多相流简介",
                "# 第2章 单个粒子运动",
                "",
                "前言内容",
                "",
                "# 第1章 多相流简介",
                "正文一",
                "# 第2章 单个粒子运动",
                "正文二",
            ]
        ),
        encoding="utf-8",
    )

    chapters = split_textbook_md(str(md))

    assert [chapter.title for chapter in chapters] == ["Preface", "第1章 多相流简介", "第2章 单个粒子运动"]
