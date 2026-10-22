from memory.core.taxonomy import detect_topics, classify_category


def test_detect_topics_with_learning_keywords():
    topics = detect_topics("今天我在学习 python 算法，晚上继续读书")
    assert "Chat" in topics
    assert "learning" in topics


def test_classify_category_with_work_keywords():
    category = classify_category("明天有项目评审会议和交付截止")
    assert category == "work"


def test_classify_category_empty_input():
    category = classify_category("")
    assert category == "uncategorized"
