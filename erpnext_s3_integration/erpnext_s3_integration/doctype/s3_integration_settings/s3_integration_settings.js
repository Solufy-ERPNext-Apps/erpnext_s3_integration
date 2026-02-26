// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("S3 Integration Settings", {
    refresh(frm) {
        frm.trigger('set_status_color');

        if (!frm.is_dirty()) {
            frm.add_custom_button(__('Test Connection'), function () {
                frm.trigger('test_connection');
            });
        }
    },

    after_save(frm) {
        frm.trigger('set_status_color');
    },

    set_status_color(frm) {
        if (!frm.doc.status) return;

        // Apply to the header badge (the nav bar)
        frm.page.clear_indicator();
        if (frm.doc.status === 'Configured & Connected') {
            frm.page.set_indicator(frm.doc.status, 'green');
        } else {
            frm.page.set_indicator(frm.doc.status, 'red');
        }
    },

    test_connection(frm) {
        if (frm.is_dirty()) {
            frappe.msgprint(__('Please save the document before testing the connection.'));
            return;
        }

        frappe.call({
            method: "erpnext_s3_integration.erpnext_s3_integration.doctype.s3_integration_settings.s3_integration_settings.test_s3_connection",
            callback: function (r) {
                if (r.message) {
                    if (r.message.success) {
                        frappe.msgprint({
                            title: __('Success'),
                            indicator: 'green',
                            message: r.message.message
                        });
                        frm.set_value('status', 'Configured & Connected');
                    } else {
                        frappe.msgprint({
                            title: __('Connection Failed'),
                            indicator: 'red',
                            message: r.message.message
                        });
                        frm.set_value('status', 'Misconfigured');
                    }
                    frm.save().then(() => {
                        frm.trigger('set_status_color');
                    });
                }
            }
        });
    },

    migrate_existing_files(frm) {
        frappe.confirm(
            __('Are you sure you want to start migrating existing files to S3? This process will run in the background.'),
            () => {
                frappe.call({
                    method: "erpnext_s3_integration.migration.start_migration",
                    args: {
                        only_unmigrated: frm.doc.migrate_only_unmigrated
                    },
                    callback: function (r) {
                        if (!r.exc) {
                            frappe.show_alert({
                                message: __(r.message),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }
        );
    },

    take_backup_and_sync(frm) {
        frappe.confirm(
            __('Are you sure you want to take a new backup and sync it to S3? This process will run in the background.'),
            () => {
                frappe.call({
                    method: "erpnext_s3_integration.erpnext_s3_integration.doctype.s3_integration_settings.s3_integration_settings.take_backup_and_sync",
                    callback: function (r) {
                        if (!r.exc) {
                            frappe.show_alert({
                                message: __(r.message),
                                indicator: 'green'
                            });
                        }
                    }
                });
            }
        );
    }
});
