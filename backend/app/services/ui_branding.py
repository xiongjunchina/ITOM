from copy import deepcopy


DEFAULT_UI_BRANDING = {
    "brand": {
        "system_name_zh": "IT运营管理平台", "system_name_en": "IT Operations Management",
        "short_name_zh": "ITOM", "short_name_en": "ITOM",
        "description_zh": "统一、透明、可度量的 IT 运营工作台",
        "description_en": "A unified, transparent and measurable IT operations workspace",
        "logo_light_url": "", "logo_dark_url": "", "logo_square_url": "", "favicon_url": "",
        "browser_title_suffix": "ITOM",
    },
    "login": {
        "title_zh": "欢迎登录", "title_en": "Welcome back", "description_zh": "", "description_en": "",
        "show_logo": True, "layout": "center", "background_type": "pattern",
        "background_color": "#f3f6fb", "background_image_url": "",
        "notice_zh": "", "notice_en": "", "help_url": "", "support_text": "",
        "privacy_url": "", "terms_url": "", "copyright": "",
    },
    "legal": {
        "developer_name_zh": "ITOM 开发团队", "developer_name_en": "ITOM Development Team",
        "vendor_name_zh": "", "vendor_name_en": "", "website_url": "", "support_url": "",
        "copyright_holder_zh": "ITOM", "copyright_holder_en": "ITOM",
        "copyright_year": "2026", "license_name_zh": "专有软件", "license_name_en": "Proprietary Software",
        "license_url": "", "third_party_notices_url": "",
    },
    "appearance": {
        "primary_color": "#2457D6", "default_theme": "light", "default_density": "default",
        "sidebar_theme": "dark", "show_system_name_in_header": False,
    },
    "roles": {
        "manager_landing": "/dashboard", "operator_landing": "/itsm/incidents",
        "requester_landing": "/itsm/catalog", "noc_landing": "/dashboard",
    },
    "announcement": {
        "enabled": False, "type": "info", "text_zh": "", "text_en": "",
        "starts_at": "", "ends_at": "", "dismissible": True, "show_on_login": True,
    },
    "environment": {"label": "production", "show_marker": False},
}


def default_config() -> dict:
    return deepcopy(DEFAULT_UI_BRANDING)


def merge_defaults(value: dict | None) -> dict:
    result = default_config()
    for section, fields in (value or {}).items():
        if section in result and isinstance(fields, dict):
            result[section].update(fields)
    return result
