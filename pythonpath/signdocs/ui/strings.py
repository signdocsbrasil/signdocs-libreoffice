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

from signdocs import validators

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
    # The old text warned that a blank sender suppressed invites. That stopped
    # being true when the server began setting `owner` from the verified
    # identity: the field could not be blank, and nothing the client sent was
    # used. Say what actually happens instead.
    "sender_hint": {
        "pt": "Os envios saem em nome da conta conectada.",
        "en": "Sends are attributed to the signed-in account.",
        "es": "Los envíos se atribuyen a la cuenta conectada.",
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
    # Says what cancelling actually does. "Confirmar cancelamento?" on its own
    # answers none of the three things a user is weighing: whether the links
    # die, whether signatures already collected are lost, and whether the send
    # comes back. Only the first is what they intend.
    "confirm_cancel": {
        "pt": "Cancelar este envio?\n\nOs links de assinatura deixam de "
              "funcionar. As assinaturas já coletadas são preservadas, e a "
              "cota não é devolvida.",
        "en": "Cancel this send?\n\nThe signing links stop working. "
              "Signatures already collected are preserved, and the allowance "
              "is not given back.",
        "es": "¿Cancelar este envío?\n\nLos enlaces de firma dejan de "
              "funcionar. Las firmas ya recogidas se conservan, y la cuota no "
              "se devuelve.",
    },
    "preserved_signatures": {"pt": "Assinaturas preservadas: %d",
                             "en": "Signatures preserved: %d",
                             "es": "Firmas conservadas: %d"},

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
    "max_signers": {"pt": "Máximo de %d signatários.",
                    "en": "At most %d signers.",
                    "es": "Máximo de %d firmantes."},
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
    # The app's own wording, verbatim, so the same rule reads the same wherever
    # somebody meets it. A subuser signs against the master's row, never one of
    # their own, so their address is not a signatory identity.
    "subuser_not_signer": {
        "pt": "Subusuários não podem ser signatários.",
        "en": "Sub-users cannot be signatories.",
        "es": "Los subusuarios no pueden ser firmantes.",
    },
    # Why the order selector is locked. The A1/A3 path loads the previous
    # signer's output, so there is an order whether or not anybody picks one.
    "order_forced_cert": {
        "pt": "Certificado exige ordem sequencial.",
        "en": "Certificates require sequential order.",
        "es": "El certificado exige orden secuencial.",
    },
    # The list order is the signing order, so these are not cosmetic on a
    # sequential send: they decide who is asked first.
    "move_up": {"pt": "Subir", "en": "Up", "es": "Subir"},
    "move_down": {"pt": "Descer", "en": "Down", "es": "Bajar"},
    "recent": {"pt": "Recentes", "en": "Recent", "es": "Recientes"},
    "recent_title": {"pt": "Signatários recentes", "en": "Recent signers",
                     "es": "Firmantes recientes"},
    "no_recent": {
        "pt": "Ninguém ainda. Os signatários dos seus envios aparecem aqui.",
        "en": "Nobody yet. Signers from your sends appear here.",
        "es": "Nadie todavía. Los firmantes de tus envíos aparecen aquí.",
    },
    "use": {"pt": "Usar", "en": "Use", "es": "Usar"},
    "sign_now": {"pt": "Assinar agora", "en": "Sign now", "es": "Firmar ahora"},
    # Marks the reader's own row in the signer list, which is also the row the
    # Assinar agora button acts on.
    "signer_you": {"pt": "(você)", "en": "(you)", "es": "(tú)"},
    # A disabled button with no explanation reads as a broken button. Here the
    # reason is the feature: you can only ever sign as yourself.
    "sign_now_other": {
        "pt": "Você só pode assinar pela sua própria conta. Este signatário "
              "recebe o link por e-mail.",
        "en": "You can only sign with your own account. This signer receives "
              "their link by e-mail.",
        "es": "Solo puedes firmar con tu propia cuenta. Este firmante recibe "
              "su enlace por correo.",
    },
    # Said plainly, because "why can't I copy this?" is the obvious question and
    # the honest answer is reassuring rather than embarrassing.
    "copy_click_only_blocked": {
        "pt": "Neste tipo de assinatura, o link sozinho já permite assinar — "
              "por isso ele vai direto para o e-mail do signatário e não pode "
              "ser copiado aqui.",
        "en": "With this signature type the link alone is enough to sign, so "
              "it goes straight to the signer's e-mail and cannot be copied "
              "here.",
        "es": "Con este tipo de firma el enlace por sí solo basta para firmar, "
              "por eso va directo al correo del firmante y no se puede copiar "
              "aquí.",
    },
    # Shown in the list in place of a link that was never sent to us.
    "link_by_email": {"pt": "link enviado por e-mail",
                      "en": "link sent by e-mail",
                      "es": "enlace enviado por correo"},
    # The link is minted on demand and never stored, so it can fail to come
    # back — say why rather than opening a blank browser tab.
    "sign_now_unavailable": {
        "pt": "Não foi possível abrir a assinatura. Ela pode já ter sido "
              "concluída ou cancelada.",
        "en": "Could not open the signature. It may already be completed or "
              "cancelled.",
        "es": "No se pudo abrir la firma. Puede que ya esté completada o "
              "cancelada.",
    },
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
    # ACTIVE is the API's word for "nobody has signed yet", which as a label
    # says nothing to the person reading it. Name the thing being waited on.
    "status_active": {"pt": "Aguardando assinatura",
                      "en": "Awaiting signature",
                      "es": "Esperando firma"},
    "status_created": {"pt": "Criado", "en": "Created", "es": "Creado"},
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
    # Used and remaining, not just remaining. "Usados 12/80" answers "how much
    # have I burned this month" and "restam 68" answers "can I send now"; the
    # second alone leaves the first to arithmetic.
    "quota_line": {"pt": "Plano %s · usados %d/%d · restam %d",
                   "en": "%s plan · used %d/%d · %d left",
                   "es": "Plan %s · usados %d/%d · quedan %d"},
    "quota_line_noplan": {"pt": "Usados %d/%d · restam %d",
                          "en": "Used %d/%d · %d left",
                          "es": "Usados %d/%d · quedan %d"},
    "quota_credits": {"pt": "Créditos avulsos · %d disponíveis",
                      "en": "Pay-per-use credits · %d available",
                      "es": "Créditos sueltos · %d disponibles"},
    "quota_blocked": {"pt": "Sem envios disponíveis neste período.",
                      "en": "No sends available in this period.",
                      "es": "Sin envíos disponibles en este período."},
    "quota_unknown": {"pt": "Não foi possível consultar o seu plano.",
                      "en": "Could not read your plan.",
                      "es": "No se pudo consultar tu plan."},
    # -- policy consent
    "consent_title": {"pt": "Termos e Privacidade", "en": "Terms and Privacy",
                      "es": "Términos y Privacidad"},
    "consent_intro": {
        "pt": "Para enviar documentos, é preciso aceitar os documentos abaixo. "
              "Abra e leia cada um antes de aceitar.",
        "en": "To send documents you must accept the documents below. Open and "
              "read each one before accepting.",
        "es": "Para enviar documentos hay que aceptar los documentos de abajo. "
              "Abre y lee cada uno antes de aceptar.",
    },
    "consent_tos": {"pt": "Termos de Uso", "en": "Terms of Use",
                    "es": "Términos de Uso"},
    "consent_privacy": {"pt": "Política de Privacidade",
                        "en": "Privacy Policy",
                        "es": "Política de Privacidad"},
    "consent_open": {"pt": "Abrir", "en": "Open", "es": "Abrir"},
    "consent_accept": {"pt": "Li e aceito", "en": "I have read and accept",
                       "es": "He leído y acepto"},
    "consent_declined": {
        "pt": "Sem o aceite dos Termos de Uso e da Política de Privacidade não "
              "é possível enviar documentos.",
        "en": "Without accepting the Terms of Use and the Privacy Policy you "
              "cannot send documents.",
        "es": "Sin aceptar los Términos de Uso y la Política de Privacidad no "
              "se pueden enviar documentos.",
    },
    "busy_consent": {"pt": "Verificando os termos aceitos…",
                     "en": "Checking accepted terms…",
                     "es": "Verificando los términos aceptados…"},
    "busy_consent_save": {"pt": "Registrando o aceite…",
                          "en": "Recording acceptance…",
                          "es": "Registrando la aceptación…"},
    # Deliberately blocking rather than warning. Unlike the quota reading,
    # which is a display the server enforces anyway, nothing server-side
    # refuses a send from a user who has not accepted -- so if the extension
    # cannot confirm acceptance it must not proceed.
    "consent_unavailable": {
        "pt": "Não foi possível verificar o aceite dos termos. Tente de novo "
              "quando houver conexão.",
        "en": "Could not verify acceptance of the terms. Try again when you "
              "have a connection.",
        "es": "No se pudo verificar la aceptación de los términos. Inténtalo "
              "de nuevo cuando haya conexión.",
    },

    # -- upgrade
    "upgrade": {"pt": "Assinar plano", "en": "Subscribe", "es": "Suscribirse"},
    "upgrade_title": {"pt": "Assinar um plano", "en": "Choose a plan",
                      "es": "Elegir un plan"},
    "upgrade_intro": {
        "pt": "Escolha um plano para continuar enviando documentos.",
        "en": "Choose a plan to keep sending documents.",
        "es": "Elige un plan para seguir enviando documentos.",
    },
    "plan_row": {"pt": "%s — %d documentos/mês — %s",
                 "en": "%s — %d documents/month — %s",
                 "es": "%s — %d documentos/mes — %s"},
    "billing": {"pt": "Cobrança", "en": "Billing", "es": "Facturación"},
    "monthly": {"pt": "Mensal", "en": "Monthly", "es": "Mensual"},
    "annual": {"pt": "Anual (cota de 12 meses de uma vez)",
               "en": "Annual (12 months of allowance at once)",
               "es": "Anual (cuota de 12 meses de una vez)"},
    "pick_a_plan": {"pt": "Selecione um plano.", "en": "Select a plan.",
                    "es": "Selecciona un plan."},
    "busy_checkout": {"pt": "Preparando o pagamento…",
                      "en": "Preparing checkout…",
                      "es": "Preparando el pago…"},
    # The extension never sees card details: they belong on Stripe's own page,
    # in the browser, never in a UNO dialog.
    "checkout_opened": {
        "pt": "Abrimos o navegador para concluir o pagamento com segurança.\n\n"
              "Depois de pagar, feche e abra esta janela de novo para ver a "
              "nova cota.",
        "en": "We opened your browser to complete the payment securely.\n\n"
              "After paying, close and reopen this window to see the new "
              "allowance.",
        "es": "Abrimos el navegador para completar el pago de forma segura."
              "\n\nDespués de pagar, cierra y abre esta ventana de nuevo para "
              "ver la nueva cuota.",
    },
    "checkout_link": {
        "pt": "Não foi possível abrir o navegador. O link foi copiado:",
        "en": "Could not open the browser. The link has been copied:",
        "es": "No se pudo abrir el navegador. El enlace fue copiado:",
    },
    "fiscal_title": {"pt": "Dados de faturamento", "en": "Billing details",
                     "es": "Datos de facturación"},
    "fiscal_intro": {
        "pt": "Precisamos destes dados uma única vez para emitir a cobrança.",
        "en": "We need these once in order to issue the invoice.",
        "es": "Necesitamos estos datos una sola vez para emitir el cobro.",
    },
    "legal_name": {"pt": "Nome ou razão social", "en": "Name or company name",
                   "es": "Nombre o razón social"},

    "quota_confirm": {
        "pt": "Sem envios disponíveis neste período. O servidor deve "
              "recusar este envio.\n\nCancelar um envio anterior não devolve "
              "a cota.\n\nContinuar mesmo assim?",
        "en": "No sends available in this period. The server will most "
              "likely refuse this one.\n\nCancelling an earlier send does not "
              "give the allowance back.\n\nContinue anyway?",
        "es": "Sin envíos disponibles en este período. El servidor "
              "probablemente rechazará este envío.\n\nCancelar un envío "
              "anterior no devuelve la cuota.\n\n¿Continuar de todos modos?",
    },
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
PROFILE_ORDER = ("click_only", "click_plus_otp", "digital_certificate")


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


#: Wire status -> string key. Sessions report ACTIVE/COMPLETED/CANCELLED/
#: EXPIRED/FAILED; envelopes add CREATED.
API_STATUS = {
    "CREATED": "status_created",
    "ACTIVE": "status_active",
    "COMPLETED": "status_completed",
    "CANCELLED": "status_cancelled",
    "EXPIRED": "status_expired",
    "FAILED": "status_failed",
}


def api_status(s, raw):
    """
    A wire status as something a person can read.

    Falls back to the raw value for anything unrecognised rather than blanking
    the field: if the API grows a status, showing `SUSPENDED` is unhelpful but
    showing nothing at all looks like the dialog failed to load. Same reasoning
    as `Strings.__call__` returning the key it could not find.

    Only ever for display — the raw value still drives whether cancel is
    offered and whether the local row is retired, and those must not be
    matched against a translated string.
    """
    if not raw:
        return ""
    key = API_STATUS.get(str(raw).strip().upper())
    return s(key) if key else str(raw)


def signer_line(s, signer, is_you=False):
    """
    One signer as a row in the tracking list.

    "Signatários: 0/1" says how many are outstanding but never which, which is
    the thing worth knowing on a multi-signer envelope — a count cannot tell
    you who to chase.

    Name, e-mail and CPF/CNPJ together, because on their own none of them
    identifies a signer reliably: two people share a name, one person has
    several addresses, and the fiscal number is the field most worth
    double-checking before a document is signed — it is the one a typo makes
    legally wrong rather than merely undeliverable.

    Every part is optional and simply left out when absent, so a row is never
    padded with empty separators. Whether the row is the reader's own is
    decided by the caller: identity comparison belongs with
    `oauth.matches_account`, not duplicated here.
    """
    who = (signer.get("name") or "").strip() or (signer.get("email") or "").strip()
    if not who:
        who = "—"
    if is_you:
        who = "%s %s" % (who, s("signer_you"))

    parts = [who]
    email = (signer.get("email") or "").strip()
    # Not repeated when it already stands in for a missing name.
    if email and email != who.split(" ")[0]:
        parts.append(email)
    fiscal = (signer.get("fiscal") or "").strip()
    if fiscal:
        parts.append(validators.format_cpf_cnpj(fiscal) or fiscal)

    state = api_status(s, signer.get("status"))
    if state:
        parts.append(state)
    return " — ".join(parts)


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
    # `used` is taken from the server when it sends it and derived only as a
    # fallback, so the two numbers on screen can never disagree with the row
    # the server is actually metering.
    used = _as_int(quota.get("used"))
    if used is None:
        used = max(0, limit - remaining)

    if plan:
        return s("quota_line") % (plan, used, limit, remaining)
    return s("quota_line_noplan") % (used, limit, remaining)


def quota_exhausted(info):
    """
    True only when the server has actually said no.

    Kept next to `quota_line` so one module owns the reading of this payload.

    Deliberately not the same thing as `quota_line` returning None. That means
    the lookup failed and nothing is known; this means it succeeded and the
    answer was no. Conflating them would let a timed-out status call stop a
    send the user is perfectly entitled to make, which is a worse failure than
    the one being prevented — so absent, unreadable or partial data is never
    exhausted.
    """
    if not isinstance(info, dict):
        return False
    quota = info.get("quota")
    if not isinstance(quota, dict):
        return False
    if quota.get("allowed") is False:
        return True
    remaining = _as_int(quota.get("remaining"))
    return remaining is not None and remaining <= 0
