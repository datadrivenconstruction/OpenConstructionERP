# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Turkish text for every notification the platform sends.

The Turkish twin of ``templates._TEMPLATES``: same keys, same ``{placeholders}``.
``tests/unit/test_notification_catalogue_tr.py`` holds the two tables equal, so
a notification added in English without its Turkish line fails the suite
instead of reaching a Turkish mailbox in English.

Wording follows site usage: RFI is "Bilgi Talebi (RFI)", a submittal is an
"Onay Belgesi", correspondence is "Yazışma", a variation is "İlave İş", a
change order is a "Değişiklik Emri", a due date is "son tarih".

Turkish attaches case endings to the noun, and the ending depends on the last
vowel of the word it joins. A placeholder is filled with a value nobody has
seen yet, so no sentence here puts an ending on one: the value is always
followed by a noun of its own ("{project} projesinde", "{code} numaralı").
"""

from __future__ import annotations

TEMPLATES_TR: dict[str, str] = {
    # BOQ
    "notifications.boq.created.title": "Keşif oluşturuldu",
    "notifications.boq.created.body": "'{boq_name}' adlı keşif cetveliniz kaydedildi.",
    # Meetings
    "notifications.meeting.action_assigned.title": "Size bir aksiyon maddesi atandı",
    "notifications.meeting.action_assigned.body": "{meeting_number} numaralı toplantıdan: {description}",
    # CDE
    "notifications.cde.state_transitioned.title": "Belge durumu değişti",
    "notifications.cde.state_transitioned.body": "Kapsayıcı '{new_state}' durumuna geçti.",
    "notifications.cde.linked_published.title": "İşinize bağlı bir belge yayımlandı",
    "notifications.cde.linked_published.body": (
        "{container_code} belgesi {revision_code} revizyonuyla yayımlandı. Bağlı kayıtlarınız: {records}."
    ),
    # RFIs
    "notifications.rfi.assigned.title": "Size bir Bilgi Talebi (RFI) atandı",
    "notifications.rfi.assigned.body": "{code} - {title}",
    "notifications.rfi.responded.title": "Bilgi Talebi (RFI) yanıtlandı",
    "notifications.rfi.responded.body": "{code} numaralı talebiniz ({title}) yanıtlandı.",
    # Risks
    "notifications.risk.assigned.title": "Size bir risk atandı",
    "notifications.risk.assigned.body": "{code} - {title}",
    # Cost overrun
    "notifications.costmodel.overrun_alert.title": "Maliyet aşımı uyarısı",
    "notifications.costmodel.overrun_alert.body": (
        "{category} maliyeti bütçeyi aştı: gerçekleşen {actual} {currency}, planlanan {planned} {currency} "
        "üzerindeki +%{threshold_pct} uyarı eşiğini geçti."
    ),
    # Submittals
    "notifications.submittal.submitted.title": "Onay Belgesi inceleme bekliyor",
    "notifications.submittal.submitted.body": "{code} - {title}",
    "notifications.submittal.approved.title": "Onay Belgesi onaylandı",
    "notifications.submittal.approved.body": "{code} - {title}",
    "notifications.submittal.rejected.title": "Onay Belgesi reddedildi",
    "notifications.submittal.rejected.body": "{code} ({title}). Gerekçe: {reason}",
    "notifications.submittal.revise_resubmit.title": "Onay Belgesi revize edilmeli",
    "notifications.submittal.revise_resubmit.body": "{code} ({title}). Gerekçe: {reason}",
    "notifications.submittal.approved_as_noted.title": "Onay Belgesi notlu onaylandı",
    "notifications.submittal.approved_as_noted.body": "{code} - {title}",
    # Transmittals
    "notifications.transmittal.issued.title": "Size bir İletim Yazısı gönderildi",
    "notifications.transmittal.issued.body": "{code} - {title}",
    "notifications.transmittal.acknowledged.title": "İletim Yazısı teslim alındı",
    "notifications.transmittal.acknowledged.body": "Alıcı {code} ({title}) kaydını teslim aldığını onayladı.",
    "notifications.transmittal.responded.title": "İletim Yazısı yanıtlandı",
    "notifications.transmittal.responded.body": "{code} ({title}). {response_summary}",
    # Singular-namespace keys
    "notification.rfi_assigned_title": "Size bir Bilgi Talebi (RFI) atandı",
    "notification.rfi_assigned_body": "Bilgi Talebi (RFI) {rfi_number} - {subject}",
    "notification.task_assigned_title": "Yeni görev atandı",
    "notification.task_assigned_body": "{task_title}",
    "notification.invoice_approved_title": "Fatura onaylandı",
    "notification.invoice_approved_body": "Fatura {invoice_number} - {amount_total} {currency_code}",
    "notification.inspection_scheduled_title": "Denetim planlandı",
    "notification.inspection_scheduled_body": "{inspection_number} - {title}, tarih: {inspection_date}",
    "notification.submittal_status_changed_title": "Onay Belgesi durumu değişti",
    "notification.submittal_status_changed_body": "{submittal_number} ({title}) - {new_status}",
    "notification.meeting_scheduled_title": "Toplantı planlandı",
    "notification.meeting_scheduled_body": "{title}, tarih: {meeting_date}",
    "notification.ncr_created_title": "Uygunsuzluk kaydı açıldı",
    "notification.ncr_created_body": "Uygunsuzluk {ncr_number} - {title} ({severity})",
    "notification.document_uploaded_title": "Belge yüklendi",
    "notification.document_uploaded_body": "{document_name}",
    # File comments
    "notifications.file_comments.mention.title": "Bir yorumda sizden bahsedildi",
    "notifications.file_comments.mention.body": '"{excerpt}"',
    # Project discussions
    "notifications.collaboration.comment_added.title": "Bir tartışmada yeni yorum",
    "notifications.collaboration.comment_added.body": 'Kayıt türü {entity_type}: "{excerpt}"',
    # Clash coordination
    "notifications.clash.high_severity.title": "Yüksek önemde çakışma tespit edildi",
    "notifications.clash.high_severity.body": "Önem derecesi {severity}, çakışan elemanlar: {a_name} / {b_name}",
    # Validation reports
    "notifications.validation.report.title": "Doğrulama sorun buldu",
    "notifications.validation.report.body": (
        "Kayıt türü {target_type}: {error_count} hata ve {warning_count} uyarı bulundu."
    ),
    # Punch list
    "notifications.punchlist.auto_created.title": "Eksik iş kaydı oluşturuldu",
    "notifications.punchlist.auto_created.body": "{title}",
    # Digests
    "notifications.digest.title": "Bildirim özeti",
    "notifications.digest.body": "Kanal: {channel}. {count} yeni güncellemeniz var.",
    # Approval SLA
    "notifications.approval.overdue.title": "Onay gecikti",
    "notifications.approval.overdue.body": (
        "Kayıt türü {target_kind}, adım {step_ordinal}: onay {hours_overdue} saat gecikti."
    ),
    "notifications.approval.escalated.title": "Onay size iletildi",
    "notifications.approval.escalated.body": (
        "Kayıt türü {target_kind}, adım {step_ordinal}: onay size iletildi (seviye {level})."
    ),
    "notifications.approval.reassigned.title": "Onay size devredildi",
    "notifications.approval.reassigned.body": "Kayıt türü {target_kind}, adım {step_ordinal}: karar artık sizde.",
    # Cross-module deadlines, plain wording for sources without a set of their own
    "notifications.deadline.overdue.title": "Gecikmiş: {title}",
    "notifications.deadline.overdue.body": 'Kaynak: {module}. "{title}" kaydı {days_overdue} gün gecikmiş.',
    "notifications.deadline.escalated.title": "Gecikmiş kayıt üst yönetime iletildi",
    "notifications.deadline.escalated.body": (
        'Kaynak: {module}. "{title}" kaydı hâlâ açık, {days_overdue} gün gecikmiş ve üst yönetime iletildi.'
    ),
    "notifications.deadline.approaching.title": "Son tarih yaklaşıyor: {title}",
    "notifications.deadline.approaching.body": 'Kaynak: {module}. "{title}" kaydı için son tarih {due_date}.',
    "notifications.deadline.built.approaching.title": "Son tarih yaklaşıyor: {title}",
    "notifications.deadline.built.approaching.body": '{module}: "{title}" için son tarih {due_date}.',
    # Site registers: deadline reminders that name the record
    "notifications.deadline.rfi.overdue.title": "Gecikmiş: Bilgi Talebi (RFI) {reference}",
    "notifications.deadline.rfi.overdue.body": (
        '{project} projesinde {reference} numaralı Bilgi Talebi (RFI) "{title}" gecikmiş: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Yanıt bekleniyor."
    ),
    "notifications.deadline.rfi.escalated.title": "Üst yönetime iletildi: Bilgi Talebi (RFI) {reference}",
    "notifications.deadline.rfi.escalated.body": (
        '{project} projesinde {reference} numaralı Bilgi Talebi (RFI) "{title}" hâlâ açık: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Kayıt size iletildi."
    ),
    "notifications.deadline.rfi.approaching.title": "Son tarih yaklaşıyor: Bilgi Talebi (RFI) {reference}",
    "notifications.deadline.rfi.approaching.body": (
        '{project} projesinde {reference} numaralı Bilgi Talebi (RFI) "{title}" için '
        "son tarih {due_date_display}. Yanıt bekleniyor."
    ),
    "notifications.deadline.submittals.overdue.title": "Gecikmiş: Onay Belgesi {reference}",
    "notifications.deadline.submittals.overdue.body": (
        '{project} projesinde {reference} numaralı Onay Belgesi "{title}" gecikmiş: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. İnceleme bekleniyor."
    ),
    "notifications.deadline.submittals.escalated.title": "Üst yönetime iletildi: Onay Belgesi {reference}",
    "notifications.deadline.submittals.escalated.body": (
        '{project} projesinde {reference} numaralı Onay Belgesi "{title}" hâlâ açık: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Kayıt size iletildi."
    ),
    "notifications.deadline.submittals.approaching.title": "Son tarih yaklaşıyor: Onay Belgesi {reference}",
    "notifications.deadline.submittals.approaching.body": (
        '{project} projesinde {reference} numaralı Onay Belgesi "{title}" için '
        "son tarih {due_date_display}. İnceleme bekleniyor."
    ),
    "notifications.deadline.correspondence.overdue.title": "Gecikmiş: Yazışma {reference}",
    "notifications.deadline.correspondence.overdue.body": (
        '{project} projesinde {reference} numaralı Yazışma "{title}" gecikmiş: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Yanıt bekleniyor."
    ),
    "notifications.deadline.correspondence.escalated.title": "Üst yönetime iletildi: Yazışma {reference}",
    "notifications.deadline.correspondence.escalated.body": (
        '{project} projesinde {reference} numaralı Yazışma "{title}" hâlâ yanıtsız: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Kayıt size iletildi."
    ),
    "notifications.deadline.correspondence.approaching.title": "Son tarih yaklaşıyor: Yazışma {reference}",
    "notifications.deadline.correspondence.approaching.body": (
        '{project} projesinde {reference} numaralı Yazışma "{title}" için '
        "son tarih {due_date_display}. Yanıt bekleniyor."
    ),
    "notifications.deadline.variations.overdue.title": "Gecikmiş: İlave İş {reference}",
    "notifications.deadline.variations.overdue.body": (
        '{project} projesinde {reference} numaralı İlave İş "{title}" gecikmiş: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Karar bekleniyor."
    ),
    "notifications.deadline.variations.escalated.title": "Üst yönetime iletildi: İlave İş {reference}",
    "notifications.deadline.variations.escalated.body": (
        '{project} projesinde {reference} numaralı İlave İş "{title}" hâlâ açık: '
        "son tarih {due_date_display}, gecikme {days_overdue} gün. Kayıt size iletildi."
    ),
    "notifications.deadline.variations.approaching.title": "Son tarih yaklaşıyor: İlave İş {reference}",
    "notifications.deadline.variations.approaching.body": (
        '{project} projesinde {reference} numaralı İlave İş "{title}" için '
        "son tarih {due_date_display}. Karar bekleniyor."
    ),
    # Variation requests (lifecycle)
    "notifications.variation.submitted.title": "İlave İş karar bekliyor: {code}",
    "notifications.variation.submitted.body": (
        '{project} projesinde {code} numaralı İlave İş "{title}" sunuldu, karar bekleniyor.'
    ),
    "notifications.variation.approved.title": "İlave İş onaylandı: {code}",
    "notifications.variation.approved.body": '{project} projesinde {code} numaralı İlave İş "{title}" onaylandı.',
    "notifications.variation.rejected.title": "İlave İş reddedildi: {code}",
    "notifications.variation.rejected.body": (
        '{project} projesinde {code} numaralı İlave İş "{title}" reddedildi ve size iade edildi.'
    ),
    "notifications.variation.rejected_reason.body": (
        '{project} projesinde {code} numaralı İlave İş "{title}" reddedildi ve size iade edildi. Gerekçe: {reason}'
    ),
    # Change orders (lifecycle)
    "notifications.changeorder.awaiting_approval.title": "Değişiklik Emri onay bekliyor: {code}",
    "notifications.changeorder.awaiting_approval.body": (
        '{project} projesinde {code} numaralı Değişiklik Emri "{title}" sunuldu, onay bekleniyor.'
    ),
    "notifications.changeorder.approved.title": "Değişiklik Emri onaylandı: {code}",
    "notifications.changeorder.approved.body": (
        '{project} projesinde {code} numaralı Değişiklik Emri "{title}" onaylandı.'
    ),
    "notifications.changeorder.rejected.title": "Değişiklik Emri reddedildi: {code}",
    "notifications.changeorder.rejected.body": (
        '{project} projesinde {code} numaralı Değişiklik Emri "{title}" reddedildi.'
    ),
    # Document approvals
    "notifications.file_approval.needs_approver.title": "Bir belge onayınızı bekliyor",
    "notifications.file_approval.needs_approver.body": "Belge türü {file_kind}: onayınız bekleniyor.",
    "notifications.file_approval.approved.title": "Belgeniz onaylandı",
    "notifications.file_approval.approved.body": "Belge türü {file_kind}: belgeniz tüm onay adımlarını geçti.",
    "notifications.file_approval.rejected.title": "Belgeniz iade edildi",
    "notifications.file_approval.rejected.body": "Belge türü {file_kind}: belgeniz reddedildi, düzeltme gerekiyor.",
    # Portal
    "notifications.portal.user_invited.title": "Portal kullanıcısı davet edildi",
    "notifications.portal.user_invited.body": "{portal_user_email} davet edildi, rol: {portal_role}.",
    "notifications.portal.message_received.title": "Yeni portal mesajı",
    "notifications.portal.message_received.body": "Gönderen: {buyer_name}. Yeni bir mesajınız var.",
}
