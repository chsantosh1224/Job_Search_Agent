from app.resume.parser import parse_text

SAMPLE = """JANE DOE
 AI Engineer | Agents | Python
 Pune, India | jane@example.com
PROFESSIONAL SUMMARY
Automation engineer with 9 years of experience building
reliable test and agent systems.
CORE SKILLS
 AI & Generative AI: LangGraph, RAG, prompt engineering
 Testing & Automation: Playwright, REST Assured
PROFESSIONAL EXPERIENCE
Independent AI Engineer | Self-employed
 Jul 2026 – Present
 Invoice Processing Agent: Built an agent that extracts invoice data and
flags exceptions for human review.
 RAG Assistant: Built a documentation chatbot.
Staff Automation Engineer | Example Corp
 May 2022 – Jun 2026
 Self-Healing Automation: Used an LLM to find alternative locators.
EDUCATION
B.Tech – Information Technology, 2014
"""


def test_splits_known_sections():
    parsed = parse_text(SAMPLE)
    assert set(parsed.sections) == {"summary", "skills", "experience", "education"}
    assert parsed.header.startswith("JANE DOE")


def test_summary_is_one_joined_chunk():
    summary = [c for c in parse_text(SAMPLE).chunks if c.section == "summary"]
    assert len(summary) == 1
    assert "building reliable test" in summary[0].content


def test_experience_bullets_keep_role_context_and_wrapped_lines():
    experience = [c for c in parse_text(SAMPLE).chunks if c.section == "experience"]
    assert [c.title for c in experience] == [
        "Invoice Processing Agent",
        "RAG Assistant",
        "Self-Healing Automation",
    ]
    invoice = experience[0]
    assert invoice.content.startswith("Independent AI Engineer | Self-employed — ")
    assert invoice.content.endswith("flags exceptions for human review.")
    assert experience[2].content.startswith("Staff Automation Engineer | Example Corp — ")


def test_skill_bullets_are_titled_by_category():
    skills = [c for c in parse_text(SAMPLE).chunks if c.section == "skills"]
    assert [c.title for c in skills] == ["AI & Generative AI", "Testing & Automation"]


def test_del_character_bullets_are_split():
    text = "CORE SKILLS\n \x7f AI: LangGraph, RAG\nChromaDB\n\x7f Testing: Playwright\n"
    skills = parse_text(text).chunks
    assert [c.title for c in skills] == ["AI", "Testing"]
    assert skills[0].content == "AI: LangGraph, RAG ChromaDB"


def test_date_lines_are_not_chunks():
    assert not any("Jul 2026" in c.content for c in parse_text(SAMPLE).chunks)
