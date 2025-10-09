define([
    'jquery',
    'underscore',
    'gettext',
    'common/js/components/utils/view_utils',
    'js/utils/modal'
], function($, _, gettext, ViewUtils, ModalUtils) {
    'use strict';

    return function() {
        var $modal = $('#course-mode-modal');
        var $form = $('#course-mode-form');
        var isEditMode = false;
        var editingModeSlug = null;

        // Initialize event handlers
        function initialize() {
            console.log('Course modes initialized');
            console.log('Modal element:', $modal);
            console.log('New button:', $('.new-course-mode-button'));

            // New course mode button
            $('.new-course-mode-button').on('click', function(e) {
                e.preventDefault();
                console.log('New course mode button clicked');
                openModal(false);
            });

            // Edit button
            $('.edit-mode-button').on('click', function(e) {
                e.preventDefault();
                var modeSlug = $(this).data('mode-slug');
                editMode(modeSlug);
            });

            // Delete button
            $('.delete-mode-button').on('click', function(e) {
                e.preventDefault();
                var modeSlug = $(this).data('mode-slug');
                deleteMode(modeSlug);
            });

            // Modal close button
            $('.modal-close, .cancel-button').on('click', function(e) {
                e.preventDefault();
                closeModal();
            });

            // Save button
            $('.save-button').on('click', function(e) {
                e.preventDefault();
                saveMode();
            });

            // Mode slug change handler
            $('#mode-slug').on('change', function() {
                updateDisplayName();
            });
        }

        // Open modal for adding or editing
        function openModal(isEdit) {
            isEditMode = isEdit;
            if (!isEdit) {
                $form[0].reset();
                $('.modal-title').text(gettext('Add Course Mode'));
                $('#mode-slug').prop('disabled', false);
            }
            $modal.css('display', 'block');
            // Force modal card height in case external CSS overrides ours
            var $modalCard = $modal.find('.modal');
            if ($modalCard.length) {
                $modalCard.css({
                    height: 'calc(100vh - 160px)',
                    maxHeight: 'calc(100vh - 160px)',
                    minHeight: '60vh'
                });
            }
        }

        // Close modal
        function closeModal() {
            $modal.css('display', 'none');
            $form[0].reset();
            isEditMode = false;
            editingModeSlug = null;
        }

        // Edit existing mode
        function editMode(modeSlug) {
            editingModeSlug = modeSlug;

            // Fetch current mode data
            $.ajax({
                url: CMS.URL.COURSE_MODES,
                method: 'GET',
                contentType: 'application/json',
                headers: {
                    Accept: 'application/json',
                    'X-CSRFToken': ViewUtils.getCookie('csrftoken')
                },
                success: function(response) {
                    var modes = response.modes || [];
                    var mode = _.find(modes, function(m) {
                        return m.mode_slug === modeSlug;
                    });

                    if (mode) {
                        populateForm(mode);
                        $('.modal-title').text(gettext('Edit Course Mode'));
                        $('#mode-slug').prop('disabled', true);
                        openModal(true);
                    }
                },
                error: function(xhr) {
                    showError(gettext('Failed to load course mode details'));
                }
            });
        }

        // Populate form with mode data
        function populateForm(mode) {
            $('#mode-slug').val(mode.mode_slug);
            $('#mode-display-name').val(mode.mode_display_name);
            $('#mode-min-price').val(mode.min_price);
            $('#mode-currency').val(mode.currency);
            $('#mode-description').val(mode.description || '');
            $('#mode-product-url').val(mode.product_url || '');
            $('#mode-sku').val(mode.sku || '');
            $('#mode-bulk-sku').val(mode.bulk_sku || '');
            if (mode.expiration_datetime) {
                // Convert datetime to local format for input
                var date = new Date(mode.expiration_datetime);
                var dateStr = date.toISOString().slice(0, 16);
                $('#mode-expiration').val(dateStr);
            }
        }

        // Update display name based on mode slug
        function updateDisplayName() {
            var modeSlug = $('#mode-slug').val();
            var displayNames = {
                audit: gettext('Audit'),
                verified: gettext('Verified Certificate'),
                honor: gettext('Honor Code Certificate'),
                professional: gettext('Professional Education'),
                'no-id-professional': gettext('Professional Education (No ID)'),
                credit: gettext('Credit'),
                masters: gettext('Masters')
            };
            if (displayNames[modeSlug] && !$('#mode-display-name').val()) {
                $('#mode-display-name').val(displayNames[modeSlug]);
            }
        }

        // Save mode (create or update)
        function saveMode() {
            var formData = {
                mode_slug: $('#mode-slug').val(),
                mode_display_name: $('#mode-display-name').val(),
                min_price: parseInt($('#mode-min-price').val()) || 0,
                currency: $('#mode-currency').val(),
                description: $('#mode-description').val(),
                product_url: $('#mode-product-url').val(),
                sku: $('#mode-sku').val(),
                bulk_sku: $('#mode-bulk-sku').val()
            };
            // Add expiration datetime if provided
            var expiration = $('#mode-expiration').val();
            if (expiration) {
                formData.expiration_datetime = new Date(expiration).toISOString();
            }
            // Validate required fields
            if (!formData.mode_slug || !formData.mode_display_name) {
                showError(gettext('Please fill in all required fields'));
                return;
            }

            var method = isEditMode ? 'PUT' : 'POST';

            $.ajax({
                url: CMS.URL.COURSE_MODES,
                method: method,
                data: JSON.stringify(formData),
                contentType: 'application/json',
                headers: {
                    Accept: 'application/json',
                    'X-CSRFToken': ViewUtils.getCookie('csrftoken')
                },
                success: function(response) {
                    closeModal();
                    showSuccess(gettext('Course mode saved successfully'));
                    // Reload the page to show updated data
                    setTimeout(function() {
                        window.location.reload();
                    }, 1000);
                },
                error: function(xhr) {
                    var error = xhr.responseJSON ? xhr.responseJSON.error : gettext('Failed to save course mode');
                    showError(error);
                }
            });
        }

        // Delete mode
        function deleteMode(modeSlug) {
            // Using ViewUtils for confirmation dialog
            // eslint-disable-next-line no-alert
            var confirmed = window.confirm(gettext('Are you sure you want to delete this course mode?'));
            if (!confirmed) {
                return;
            }

            $.ajax({
                url: CMS.URL.COURSE_MODES,
                method: 'DELETE',
                data: JSON.stringify({mode_slug: modeSlug}),
                contentType: 'application/json',
                headers: {
                    Accept: 'application/json',
                    'X-CSRFToken': ViewUtils.getCookie('csrftoken')
                },
                success: function(response) {
                    showSuccess(gettext('Course mode deleted successfully'));
                    // Remove the row from table
                    $('tr[data-mode-slug="' + modeSlug + '"]').fadeOut(400, function() {
                        $(this).remove();
                        // Check if table is empty
                        if ($('.course-mode-row').length === 0) {
                            location.reload();
                        }
                    });
                },
                error: function(xhr) {
                    var error = xhr.responseJSON ? xhr.responseJSON.error : gettext('Failed to delete course mode');
                    showError(error);
                }
            });
        }

        // Show success message
        function showSuccess(message) {
            ViewUtils.showMessage({
                title: gettext('Success'),
                message: message,
                type: 'confirmation'
            });
        }

        // Show error message
        function showError(message) {
            ViewUtils.showMessage({
                title: gettext('Error'),
                message: message,
                type: 'error'
            });
        }

        // Initialize on page load
        $(document).ready(function() {
            initialize();
        });
    };
});
