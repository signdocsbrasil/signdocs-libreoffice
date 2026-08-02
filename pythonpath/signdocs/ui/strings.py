# SPDX-License-Identifier: MPL-2.0
"""
UI strings, keyed by the office's own locale.

Externalised from day one. The ONLYOFFICE plugin hardcodes every string in
pt-BR and has no string table, which is fine for a Brazilian-only plugin
shipped from our own site but not for a listing on
extensions.libreoffice.org, where the audience is global by default.

pt-BR is the fallback rather than English: this is an ICP-Brasil product, and
a Brazilian user seeing English because locale detection hiccuped is a worse
outcome than the reverse.
"""

DEFAULT_LANG = "pt"

_STRINGS = {
    # -- window titles
    "app": {"pt": "SignDocs Brasil", "en": "SignDocs Brasil", "es": "SignDocs Brasil"},
    "send_title": {"pt": "Enviar para assinatura",
                   "en": "Send for signature", "es": "Enviar para firma"},
    "review_title": {"pt": "Conferir envio", "en": "Review",
                     "es": "Revisar envío"},
    "result_title": {"pt": "Enviado", "en": "Sent", "es": "Enviado"},
    "track_title": {"pt": "Acompanhar", "en": "Track", "es": "Seguimiento"},
    "settings_title": {"pt": "Configurações", "en": "Settings",
                       "es": "Configuración"},
    "history_title": {"pt": "Envios recentes", "en": "Recent sends",
                      "es": "Envíos recientes"},
    "signer_title": {"pt": "Signatário", "en": "Signer", "es": "Firmante"},
    "connect_title": {"pt": "Conectar", "en": "Connect", "es": "Conectar"},

    # -- fields
    "sender": {"pt": "Remetente", "en": "Sender", "es": "Remitente"},
    "sender_hint": {
        "pt": "Sem o remetente, a API não envia convites por e-mail.",
        "en": "Without a sender, the API dispatches no invitation e-mails.",
        "es": "Sin remitente, la API no envía invitaciones por correo.",
    },
    "sig_type": {"pt": "Tipo de assinatura", "en": "Signature type",
                 "es": "Tipo de firma"},
    "order": {"pt": "Ordem", "en": "Order", "es": "Orden"},
    "signers": {"pt": "Signatários", "en": "Signers", "es": "Firmantes"},
    "name": {"pt": "Nome", "en": "Name", "es": "Nombre"},
    "email": {"pt": "E-mail", "en": "E-mail", "es": "Correo"},
    "fiscal": {"pt": "CPF ou CNPJ", "en": "CPF or CNPJ", "es": "CPF o CNPJ"},
    "document": {"pt": "Documento", "en": "Document", "es": "Documento"},

    # -- signature profiles
    "click_only": {"pt": "Clique simples", "en": "Click only",
                   "es": "Clic simple"},
    "click_plus_otp": {"pt": "Clique + código por e-mail",
                       "en": "Click + e-mail code",
                       "es": "Clic + código por correo"},
    "biometric": {"pt": "Biometria facial", "en": "Facial biometrics",
                  "es": "Biometría facial"},
    "digital_certificate": {"pt": "Certificado digital ICP-Brasil",
                            "en": "ICP-Brasil digital certificate",
                            "es": "Certificado digital ICP-Brasil"},

    # -- order
    "parallel": {"pt": "Paralela (todos ao mesmo tempo)",
                 "en": "Parallel (everyone at once)",
                 "es": "Paralela (todos a la vez)"},
    "sequential": {"pt": "Sequencial (um após o outro)",
                   "en": "Sequential (one after another)",
                   "es": "Secuencial (uno tras otro)"},

    # -- buttons
    "add": {"pt": "Adicionar", "en": "Add", "es": "Añadir"},
    "edit": {"pt": "Editar", "en": "Edit", "es": "Editar"},
    "remove": {"pt": "Remover", "en": "Remove", "es": "Quitar"},
    "cancel": {"pt": "Cancelar", "en": "Cancel", "es": "Cancelar"},
    "back": {"pt": "Voltar", "en": "Back", "es": "Volver"},
    "review": {"pt": "Conferir", "en": "Review", "es": "Revisar"},
    "send_now": {"pt": "Enviar agora", "en": "Send now", "es": "Enviar ahora"},
    "close": {"pt": "Fechar", "en": "Close", "es": "Cerrar"},
    "copy": {"pt": "Copiar", "en": "Copy", "es": "Copiar"},
    "ok": {"pt": "OK", "en": "OK", "es": "OK"},
    "connect": {"pt": "Conectar", "en": "Connect", "es": "Conectar"},
    "disconnect": {"pt": "Desconectar", "en": "Disconnect", "es": "Desconectar"},
    "refresh": {"pt": "Atualizar", "en": "Refresh", "es": "Actualizar"},
    "download": {"pt": "Baixar assinado", "en": "Download signed",
                 "es": "Descargar firmado"},
    "cancel_send": {"pt": "Cancelar envio", "en": "Cancel send",
                    "es": "Cancelar envío"},
    "confirm_cancel": {"pt": "Confirmar cancelamento?",
                       "en": "Confirm cancellation?",
                       "es": "¿Confirmar cancelación?"},

    # -- states / messages
    "busy_export": {"pt": "Convertendo o documento para PDF…",
                    "en": "Converting the document to PDF…",
                    "es": "Convirtiendo el documento a PDF…"},
    "busy_send": {"pt": "Enviando…", "en": "Sending…", "es": "Enviando…"},
    "busy_connect": {"pt": "Aguardando a autorização no navegador…",
                     "en": "Waiting for authorisation in the browser…",
                     "es": "Esperando la autorización en el navegador…"},
    "busy_status": {"pt": "Consultando…", "en": "Checking…",
                    "es": "Consultando…"},
    "busy_download": {"pt": "Baixando o documento assinado…",
                      "en": "Downloading the signed document…",
                      "es": "Descargando el documento firmado…"},
    "not_connected": {
        "pt": "Conecte-se à sua conta SignDocs para enviar documentos.",
        "en": "Connect to your SignDocs account to send documents.",
        "es": "Conéctate a tu cuenta SignDocs para enviar documentos.",
    },
    "connected_as": {"pt": "Conectado", "en": "Connected", "es": "Conectado"},
    "no_signers": {"pt": "Adicione pelo menos um signatário.",
                   "en": "Add at least one signer.",
                   "es": "Añade al menos un firmante."},
    "no_history": {"pt": "Nenhum envio recente.", "en": "No recent sends.",
                   "es": "Ningún envío reciente."},
    "sent_ok": {"pt": "Envio criado. Links por signatário:",
                "en": "Send created. Per-signer links:",
                "es": "Envío creado. Enlaces por firmante:"},
    "copied": {"pt": "Link copiado.", "en": "Link copied.",
               "es": "Enlace copiado."},
    "invite_sent": {"pt": "convite enviado", "en": "invitation sent",
                    "es": "invitación enviada"},
    "invite_not_sent": {"pt": "sem convite — envie o link você mesmo",
                        "en": "no invitation — send the link yourself",
                        "es": "sin invitación — envía el enlace tú mismo"},
    "saved_to": {"pt": "Documento assinado salvo em:",
                 "en": "Signed document saved to:",
                 "es": "Documento firmado guardado en:"},
    "stage": {"pt": "Ambiente", "en": "Environment", "es": "Entorno"},
    "stage_prod": {"pt": "Produção", "en": "Production", "es": "Producción"},
    "stage_hml": {"pt": "Homologação (testes)", "en": "Homologation (testing)",
                  "es": "Homologación (pruebas)"},
    "error": {"pt": "Erro", "en": "Error", "es": "Error"},

    # -- send states. The keys are history.py's own status values, so a row
    # can be labelled with s("status_" + entry["status"]).
    "status_pending": {"pt": "Pendente", "en": "Pending", "es": "Pendiente"},
    "status_completed": {"pt": "Concluído", "en": "Completed",
                         "es": "Completado"},
    "status_cancelled": {"pt": "Cancelado", "en": "Cancelled",
                         "es": "Cancelado"},
    "status_expired": {"pt": "Expirado", "en": "Expired", "es": "Expirado"},
    "status_failed": {"pt": "Falhou", "en": "Failed", "es": "Falló"},
    "only_pending": {"pt": "Somente pendentes", "en": "Pending only",
                     "es": "Solo pendientes"},
    "pending_count": {"pt": "%d pendente(s) de %d",
                      "en": "%d pending of %d",
                      "es": "%d pendiente(s) de %d"},
    "busy_refresh": {"pt": "Atualizando os envios pendentes…",
                     "en": "Refreshing pending sends…",
                     "es": "Actualizando los envíos pendientes…"},
    "refresh_failed": {
        "pt": "%d envio(s) não puderam ser consultados. Continuam pendentes.",
        "en": "%d send(s) could not be checked. They remain pending.",
        "es": "%d envío(s) no pudieron consultarse. Siguen pendientes.",
    },

    # -- plan and quota
    "plan": {"pt": "Plano", "en": "Plan", "es": "Plan"},
    "quota_line": {"pt": "Plano %s · restam %d de %d envios",
                   "en": "%s plan · %d of %d sends left",
                   "es": "Plan %s · quedan %d de %d envíos"},
    "quota_line_noplan": {"pt": "Restam %d de %d envios",
                          "en": "%d of %d sends left",
                          "es": "Quedan %d de %d envíos"},
    "quota_credits": {"pt": "Créditos avulsos · %d disponíveis",
                      "en": "Pay-per-use credits · %d available",
                      "es": "Créditos sueltos · %d disponibles"},
    "quota_blocked": {"pt": "Sem envios disponíveis neste período.",
                      "en": "No sends available in this period.",
                      "es": "Sin envíos disponibles en este período."},
    "quota_unknown": {"pt": "Não foi possível consultar o seu plano.",
                      "en": "Could not read your plan.",
                      "es": "No se pudo consultar tu plan."},
    "quota_shared": {
        "pt": "A cota é uma só, compartilhada com o aplicativo e as demais "
              "integrações.",
        "en": "The allowance is a single pool, shared with the app and every "
              "other integration.",
        "es": "La cuota es una sola, compartida con la aplicación y las demás "
              "integraciones.",
    },
}

#: Profile keys in the order the dropdown offers them.
PROFILE_ORDER = ("click_only", "click_plus_otp", "digital_certificate", "biometric")


def _lang_from_locale(locale):
    if not locale:
        return DEFAULT_LANG
    primary = str(locale).replace("_", "-").split("-")[0].lower()
    return primary if primary in ("pt", "en", "es") else DEFAULT_LANG


def office_lang(ctx):
    """
    The office UI language, reduced to one of pt/en/es.

    Never raises: a locale lookup failing is not a reason to refuse to draw a
    dialog, so it degrades to pt-BR.
    """
    try:
        from com.sun.star.beans import PropertyValue

        provider = ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.configuration.ConfigurationProvider", ctx
        )
        arg = PropertyValue()
        arg.Name = "nodepath"
        arg.Value = "/org.openoffice.Setup/L10N"
        node = provider.createInstanceWithArguments(
            "com.sun.star.configuration.ConfigurationAccess", (arg,)
        )
        return _lang_from_locale(node.getByName("ooLocale"))
    except Exception:
        return DEFAULT_LANG


class Strings(object):
    """Bound to one language. `s("send_title")` reads better than a dict lookup."""

    def __init__(self, lang=DEFAULT_LANG):
        self.lang = lang if lang in ("pt", "en", "es") else DEFAULT_LANG

    def __call__(self, key):
        entry = _STRINGS.get(key)
        if not entry:
            # A missing key is a bug, but showing the key beats showing
            # nothing and beats raising inside a dialog builder.
            return key
        return entry.get(self.lang) or entry[DEFAULT_LANG]


def for_office(ctx):
    return Strings(office_lang(ctx))


def _as_int(value):
    """
    An int that is genuinely an int.

    `isinstance(True, int)` is True in Python, and a bool arriving where a
    count belongs would render as "restam 1 de 3" — plausible enough that
    nobody would question it. Reject bools explicitly.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def quota_line(s, info):
    """
    One line describing the plan and what is left of it, or None.

    `info` is the `/init-session` response verbatim. Returning None when there
    is nothing trustworthy to say lets the caller omit the line entirely
    rather than draw a placeholder — an empty row reads as a rendering bug,
    and a wrong number is worse than no number when it concerns billing.

    `limit` is taken from the server and never derived from the plan name.
    They genuinely disagree: a planless user is written a `Gratuito` customer
    record whose `getPlanLimit` would say 5, while the quota that is actually
    enforced comes from the shared free pool and is 3.
    """
    if not isinstance(info, dict):
        return None
    quota = info.get("quota")
    if not isinstance(quota, dict):
        return None

    remaining = _as_int(quota.get("remaining"))
    limit = _as_int(quota.get("limit"))
    if remaining is None or limit is None:
        return None

    # `allowed` is the server's own decision and outranks arithmetic: a
    # blocked channel gate reports remaining > 0 and still refuses the send.
    if quota.get("allowed") is False or remaining <= 0:
        return s("quota_blocked")

    if quota.get("source") == "credits":
        return s("quota_credits") % remaining

    plan = (info.get("user") or {}).get("plan") if isinstance(info.get("user"), dict) else None
    if plan:
        return s("quota_line") % (plan, remaining, limit)
    return s("quota_line_noplan") % (remaining, limit)
