"""设施分类与检索策略的单元测试。"""

from app.core import constants
from app.services.poi import _category_query, classify_poi


def test_classify_prefers_school_over_pharmacy():
    """匹配顺序敏感：名称同时含『小学』与『药店』时应归为小学。

    FACILITY_CATEGORIES 中「小学」排在「药店」之前，
    若顺序被无意调整，这个用例会失败。
    """
    assert classify_poi("实验小学门口大参林药店") == "小学"


def test_classify_common_categories():
    assert classify_poi("大参林药店") == "药店"
    assert classify_poi("莞城中心菜市场") == "菜市场"
    assert classify_poi("中国农业银行莞城支行") == "银行"
    assert classify_poi("沙县小吃") == "餐饮"
    assert classify_poi("莞城社区卫生服务中心") == "医疗"
    assert classify_poi("阳光幼儿园") == "幼儿园"


def test_classify_unknown_falls_back_to_other():
    assert classify_poi("环球经贸中心") == "其他"


def test_category_query_uses_dollar_union():
    """同一类别内的多个近义关键词以 $ 取并集，检索词与分类口径同源。

    逐类检索时每个请求的 query 由 _category_query 拼接：
    直接复用 FACILITY_CATEGORIES 的同义词，避免「分类表」与「检索词表」
    各维护一份而逐渐失配。
    """
    for category, keywords in constants.FACILITY_CATEGORIES.items():
        query = _category_query(category)
        assert len(query.split("$")) == len(keywords), category
        # 百度圆形区域检索的多关键字上限为 10 个
        assert len(keywords) <= 10, f"{category} 的同义关键词超过百度上限"


def test_category_query_falls_back_to_category_name():
    """类别未定义关键词时直接以类别名检索，而不是返回空串。"""
    assert _category_query("尚未定义的类别") == "尚未定义的类别"


def test_blindspot_categories_are_subset_of_defined():
    """判定盲区的类别必须已定义，否则检索时查不到数据。"""
    assert set(constants.BLINDSPOT_CATEGORIES).issubset(
        set(constants.FACILITY_CATEGORIES.keys())
    )


def test_page_size_within_baidu_limit():
    """百度地点检索单次最多返回 20 条。"""
    assert 1 <= constants.POI_PAGE_SIZE <= 20
    assert constants.POI_MAX_PAGES >= 1
