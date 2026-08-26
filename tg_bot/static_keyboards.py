from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
from tg_bot import CBT
from locales.localizer import Localizer

localizer = Localizer()
_ = localizer.translate


def CLEAR_STATE_BTN() -> K:
    return K().add(B(_("gl_cancel"), callback_data=CBT.CLEAR_STATE))


def REFRESH_BTN() -> K:
    return K().add(B(_("gl_refresh"), callback_data=CBT.UPDATE_PROFILE))


def SETTINGS_SECTIONS() -> K:
    return K() \
        .row(B("⚙️ Автоматизация", callback_data="plata_menu:automation"),
             B("🔔 Уведомления", callback_data="plata_menu:notifications")) \
        .row(B(_("mm_accounts"), callback_data="plata_menu:accounts"),
             B(_("mm_stats"), callback_data="plata_menu:stats")) \
        .row(B(_("mm_templates"), callback_data=f"{CBT.TMPLT_LIST}:0"),
             B(_("mm_plugins"), callback_data="plata_menu:plugins")) \
        .row(B("📦 Автовыдача", callback_data=f"{CBT.CATEGORY}:ad"),
             B("🤖 Автоответчик", callback_data=f"{CBT.CATEGORY}:ar")) \
        .row(B("👋 Приветствия", callback_data=f"{CBT.CATEGORY}:gr"),
             B("✅ Подтверждение заказа", callback_data=f"{CBT.CATEGORY}:oc")) \
        .add(B("🦊 Модули", callback_data="plata_menu:modules")) \
        .add(B(_("mm_more"), callback_data=CBT.MAIN2))


def SETTINGS_SECTIONS_2() -> K:
    return K() \
        .add(B(_("mm_new_msg_view"), callback_data=f"{CBT.CATEGORY}:mv")) \
        .add(B(_("mm_blacklist"), callback_data=f"{CBT.CATEGORY}:bl")) \
        .add(B(_("mm_configs"), callback_data=CBT.CONFIG_LOADER)) \
        .add(B(_("mm_authorized_users"), callback_data=f"{CBT.AUTHORIZED_USERS}:0")) \
        .add(B(_("mm_proxy"), callback_data=f"{CBT.PROXY}:0")) \
        .add(B(_("mm_language"), callback_data=f"{CBT.CATEGORY}:lang")) \
        .add(B(_("gl_back"), callback_data=CBT.MAIN))


def AR_SETTINGS() -> K:
    return K() \
        .add(B(_("ar_edit_commands"), callback_data=f"{CBT.CMD_LIST}:0")) \
        .add(B(_("ar_add_command"), callback_data=CBT.ADD_CMD)) \
        .add(B(_("gl_back"), callback_data=CBT.MAIN))


def AD_SETTINGS() -> K:
    return K() \
        .add(B(_("ad_edit_autodelivery"), callback_data=f"{CBT.AD_LOTS_LIST}:0")) \
        .add(B(_("ad_add_autodelivery"), callback_data=f"{CBT.FP_LOTS_LIST}:0")) \
        .add(B(_("ad_edit_goods_file"), callback_data=f"{CBT.PRODUCTS_FILES_LIST}:0")) \
        .row(B(_("ad_upload_goods_file"), callback_data=CBT.UPLOAD_PRODUCTS_FILE),
             B(_("ad_create_goods_file"), callback_data=CBT.CREATE_PRODUCTS_FILE)) \
        .add(B(_("gl_back"), callback_data=CBT.MAIN))


def CONFIGS_UPLOADER() -> K:
    return K() \
        .add(B(_("cfg_download_main"), callback_data=f"{CBT.DOWNLOAD_CFG}:main")) \
        .add(B(_("cfg_download_ar"), callback_data=f"{CBT.DOWNLOAD_CFG}:autoResponse")) \
        .add(B(_("cfg_download_ad"), callback_data=f"{CBT.DOWNLOAD_CFG}:autoDelivery")) \
        .add(B(_("cfg_upload_main"), callback_data="upload_main_config")) \
        .add(B(_("cfg_upload_ar"), callback_data="upload_auto_response_config")) \
        .add(B(_("cfg_upload_ad"), callback_data="upload_auto_delivery_config")) \
        .add(B(_("gl_back"), callback_data=CBT.MAIN2))

def UPLOAD_PLUGIN() -> K:
    return K().add(B(_("gl_cancel"), callback_data=CBT.CLEAR_STATE))
