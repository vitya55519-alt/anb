from services.adaptation_service import detect_language


def test_language_detection():
    assert detect_language('Привет, как дела?')[0] == 'ru'
    assert detect_language('Hey, how are you doing?')[0] == 'en'
    assert detect_language('你好，今天怎么样？')[0] == 'zh'
