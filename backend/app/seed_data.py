from __future__ import annotations

WATCHLIST_SEED = [
    {"canonical_name": "台北市立動物園", "entity_type": "zoo", "aliases": ["木柵動物園", "台北動物園"], "priority": 1, "refresh_interval_hours": 24, "default_mode": "general"},
    {"canonical_name": "新竹市立動物園", "entity_type": "zoo", "aliases": ["新竹動物園"], "priority": 1, "refresh_interval_hours": 24, "default_mode": "general"},
    {"canonical_name": "壽山動物園", "entity_type": "zoo", "aliases": ["高雄壽山動物園"], "priority": 1, "refresh_interval_hours": 24, "default_mode": "general"},
    {"canonical_name": "頑皮世界野生動物園", "entity_type": "zoo", "aliases": ["頑皮世界"], "priority": 2, "refresh_interval_hours": 24, "default_mode": "general"},
    {"canonical_name": "六福村野生動物王國", "entity_type": "zoo", "aliases": ["六福村動物園"], "priority": 2, "refresh_interval_hours": 24, "default_mode": "general"},
]

ENTITY_PAGE_SEED = [
    {
        "canonical_name": "台北市立動物園",
        "headline": "台灣指標型公立動物園的長期觀察頁",
        "introduction": "台北市立動物園位於台北市文山區木柵，是台灣規模最大的公立動物園之一。這個實體頁會持續累積園區基本介紹、資料庫整理摘要、公開圖片與使用者評論，方便後續長期追蹤動物福利、環境管理與公開回應。",
        "location": "台北市文山區新光路二段 30 號",
        "cover_image_url": "https://www.zoo.gov.taipei/images/share.jpg",
        "cover_image_alt": "台北市立動物園官方分享圖",
        "gallery": [
            {
                "url": "https://www.zoo.gov.taipei/images/share.jpg",
                "alt_text": "台北市立動物園官方分享圖",
                "caption": "可作為這個實體頁的封面與介紹圖。",
            },
        ],
    },
]

GENERAL_QUESTION_TEMPLATES = {
    "default": [
        ("一般查核問題", "近期整體公開評價偏正面還是偏負面？"),
        ("一般查核問題", "有哪些官方說法、新聞與第三方資料可交叉參考？"),
        ("近期爭議與待查問題", "最近有哪些公開討論、聲明或待查事項？"),
        ("近期爭議與待查問題", "目前哪些部分已有公開資料，哪些仍待進一步查核？"),
    ],
    "zoo": [
        ("照護與飼養環境問題", "有哪些公開資料提到飼養環境、衛生、空間或照護品質？"),
        ("一般查核問題", "近期是否有與展演、互動或動物管理有關的新聞與評論？"),
    ],
    "shelter": [
        ("收容／繁殖／救援問題", "近期是否有收容壓力、送養流程或安置問題的公開資料？"),
        ("照護與飼養環境問題", "有哪些資訊提到環境清潔、醫療照護或收容密度？"),
    ],
    "rescue_org": [
        ("收容／繁殖／救援問題", "近期是否有救援流程、安置、送養或募款相關公開資料？"),
        ("一般查核問題", "有哪些第一手紀錄、官方說明或第三方資料可以交叉參考？"),
    ],
}

ANIMAL_LAW_QUESTION_TEMPLATES = {
    "default": [
        ("動保法／法規風險問題", "依目前公開資料，是否可能涉及動保法或主管機關稽查議題？"),
        ("照護與飼養環境問題", "有哪些內容明確提到動物福利、照護或飼養環境疑慮？"),
        ("近期爭議與待查問題", "目前可支持哪些動物福利疑慮，哪些仍待進一步查核？"),
        ("近期爭議與待查問題", "近期是否有裁罰、改善要求、官方說明或待查事項？"),
    ],
    "zoo": [
        ("照護與飼養環境問題", "近期是否有受傷、死亡、惡臭、疾病或照護不足的公開描述？"),
        ("收容／繁殖／救援問題", "是否有資訊提到圈養管理、繁殖、收容或展演爭議？"),
    ],
    "shelter": [
        ("收容／繁殖／救援問題", "近期是否有超收、棄養、安置壓力或收容量相關疑慮？"),
        ("動保法／法規風險問題", "是否有公開資料提到稽查、裁罰、改善要求或主管機關回應？"),
    ],
    "rescue_org": [
        ("收容／繁殖／救援問題", "近期是否有救援、安置、送養或繁殖管理相關疑慮？"),
        ("動保法／法規風險問題", "依目前公開資料，是否有與動保法、募款透明或稽查有關的待查事項？"),
    ],
}


def question_templates_for(entity_type: str, search_mode: str) -> list[tuple[str, str]]:
    template_map = ANIMAL_LAW_QUESTION_TEMPLATES if search_mode == "animal_law" else GENERAL_QUESTION_TEMPLATES
    return [
        *template_map.get("default", []),
        *template_map.get(entity_type, []),
    ]