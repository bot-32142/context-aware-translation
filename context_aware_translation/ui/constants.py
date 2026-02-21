"""Constants for the UI module."""

from typing import Final

# Application version
APP_VERSION: Final[str] = "0.1.1"

# Language presets: (Display Name in native script, Internal Chinese name)
# All languages supported by Gemini, ranked by population of native speakers
LANGUAGES: Final[list[tuple[str, str]]] = [
    ("中文（简体）", "简体中文"),
    ("中文（繁體）", "繁体中文"),
    ("Español", "西班牙语"),
    ("English", "英语"),
    ("हिन्दी", "印地语"),
    ("العربية", "阿拉伯语"),
    ("Português", "葡萄牙语"),
    ("বাংলা", "孟加拉语"),
    ("Русский", "俄语"),
    ("日本語", "日语"),
    ("ਪੰਜਾਬੀ", "旁遮普语"),
    ("मराठी", "马拉地语"),
    ("తెలుగు", "泰卢固语"),
    ("Türkçe", "土耳其语"),
    ("தமிழ்", "泰米尔语"),
    ("Bahasa Melayu", "马来语"),
    ("Deutsch", "德语"),
    ("한국어", "韩语"),
    ("Français", "法语"),
    ("Tiếng Việt", "越南语"),
    ("اردو", "乌尔都语"),
    ("فارسی", "波斯语"),
    ("Italiano", "意大利语"),
    ("ไทย", "泰语"),
    ("ગુજરાતી", "古吉拉特语"),
    ("Polski", "波兰语"),
    ("ಕನ್ನಡ", "卡纳达语"),
    ("Bahasa Indonesia", "印尼语"),
    ("മലയാളം", "马拉雅拉姆语"),
    ("Українська", "乌克兰语"),
    ("Filipino", "菲律宾语"),
    ("Română", "罗马尼亚语"),
    ("Nederlands", "荷兰语"),
    ("Kiswahili", "斯瓦希里语"),
    ("Ελληνικά", "希腊语"),
    ("Magyar", "匈牙利语"),
    ("Čeština", "捷克语"),
    ("Svenska", "瑞典语"),
    ("Български", "保加利亚语"),
    ("עברית", "希伯来语"),
    ("Dansk", "丹麦语"),
    ("Suomi", "芬兰语"),
    ("Hrvatski", "克罗地亚语"),
    ("Slovenčina", "斯洛伐克语"),
    ("Norsk", "挪威语"),
    ("Lietuvių", "立陶宛语"),
    ("Slovenščina", "斯洛文尼亚语"),
    ("Latviešu", "拉脱维亚语"),
    ("Eesti", "爱沙尼亚语"),
]

# Default window dimensions
DEFAULT_WINDOW_WIDTH: Final[int] = 1200
DEFAULT_WINDOW_HEIGHT: Final[int] = 800
MIN_WINDOW_WIDTH: Final[int] = 800
MIN_WINDOW_HEIGHT: Final[int] = 600

# Sidebar width
SIDEBAR_WIDTH: Final[int] = 200

# Table defaults
DEFAULT_PAGE_SIZE: Final[int] = 50
