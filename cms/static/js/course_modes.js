(function() {
    'use strict';

    var courseModesUrl = window.courseModesUrl || '';
    var isEditMode = false;
    var editingModeSlug = null;
    var pendingDeleteModeSlug = null;

    // Custom notification system
    function showNotification(title, message, type) {
        type = type || 'success';
        var container = document.getElementById('notification-container');

        var iconMap = {
            success: 'fa-check-circle',
            error: 'fa-times-circle',
            warning: 'fa-exclamation-triangle'
        };

        var notification = document.createElement('div');
        notification.className = 'notification ' + type;
        notification.innerHTML = '<span class="notification-icon fa ' + iconMap[type] + '"></span>'
            + '<div class="notification-content">'
            + '<div class="notification-title">' + title + '</div>'
            + '<div class="notification-message">' + message + '</div>'
            + '</div>'
            + '<button class="notification-close" aria-label="Close">&times;</button>';

        container.appendChild(notification);

        // Close button handler
        notification.querySelector('.notification-close').addEventListener('click', function() {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(function() {
                notification.remove();
            }, 300);
        });

        // Auto-remove after 15 seconds
        setTimeout(function() {
            if (notification.parentNode) {
                notification.style.animation = 'slideOut 0.3s ease-out';
                setTimeout(function() {
                    notification.remove();
                }, 300);
            }
        }, 15000);
    }

    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function openModal(forEdit) {
        isEditMode = forEdit || false;
        var modal = document.getElementById('course-mode-modal');
        var modalTitle = document.querySelector('.modal-title');

        if (!isEditMode) {
            document.getElementById('course-mode-form').reset();
            modalTitle.textContent = 'Add Course Mode';
            document.getElementById('mode-slug').disabled = false;
        } else {
            modalTitle.textContent = 'Edit Course Mode';
            document.getElementById('mode-slug').disabled = true;
        }

        if (modal) {
            modal.style.display = 'block';
            // Force modal card height in case external CSS overrides ours
            var modalCard = modal.querySelector('.modal');
            if (modalCard) {
                modalCard.style.height = 'calc(100vh - 120px)';
                modalCard.style.maxHeight = 'calc(100vh - 120px)';
                modalCard.style.minHeight = '65vh';
            }
        }
    }

    function closeModal() {
        var modal = document.getElementById('course-mode-modal');
        if (modal) {
            modal.style.display = 'none';
            document.getElementById('course-mode-form').reset();
            isEditMode = false;
            editingModeSlug = null;
        }
    }

    function saveMode() {
        var form = document.getElementById('course-mode-form');
        var modeSlug = document.getElementById('mode-slug').value;
        var displayName = document.getElementById('mode-display-name').value;
        var minPrice = parseInt(document.getElementById('mode-min-price').value) || 0;
        var currency = document.getElementById('mode-currency').value;
        var expiration = document.getElementById('mode-expiration').value;
        var description = document.getElementById('mode-description').value;
        var productUrl = document.getElementById('mode-product-url').value;
        var sku = document.getElementById('mode-sku').value;
        var bulkSku = document.getElementById('mode-bulk-sku').value;

        // Validate required fields
        if (!modeSlug || !displayName) {
            showNotification('Required Fields Missing', 'Please fill in Mode Type and Display Name', 'warning');
            return;
        }

        var data = {
            mode_slug: modeSlug,
            mode_display_name: displayName,
            min_price: minPrice,
            currency: currency
        };

        // Only add optional fields if they have values
        if (description) {
            data.description = description;
        }
        if (productUrl) {
            data.product_url = productUrl;
        }
        if (sku) {
            data.sku = sku;
        }
        if (bulkSku) {
            data.bulk_sku = bulkSku;
        }
        if (expiration) {
            data.expiration_datetime = new Date(expiration).toISOString();
        }

        var method = isEditMode ? 'PUT' : 'POST';
        var csrftoken = getCookie('csrftoken');

        console.log('Saving mode:', method, data);

        fetch(courseModesUrl, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify(data)
        })
            .then(function(response) {
                console.log('Response status:', response.status);
                // eslint-disable-next-line no-shadow
                return response.json().then(function(data) {
                    return {status: response.status, data: data};
                });
            })
            .then(function(result) {
                if (result.status >= 200 && result.status < 300) {
                    var title = isEditMode ? 'Mode Updated' : 'Mode Created';
                    var message = isEditMode ? 'Course mode has been updated successfully' : 'New course mode has been created successfully';
                    showNotification(title, message, 'success');
                    closeModal();
                    setTimeout(function() {
                        location.reload();
                    }, 1000);
                } else {
                    var errorMsg = result.data.error || result.data.errors || JSON.stringify(result.data);
                    console.error('Server error:', result.data);
                    showNotification('Error', errorMsg, 'error');
                }
            })
            .catch(function(error) {
                console.error('Fetch error:', error);
                showNotification('Error', error.message, 'error');
            });
    }

    function editMode(modeSlug) {
        isEditMode = true;
        editingModeSlug = modeSlug;

        // Fetch full mode data from backend
        var csrftoken = getCookie('csrftoken');
        fetch(courseModesUrl, {
            method: 'GET',
            headers: {
                Accept: 'application/json',
                'X-CSRFToken': csrftoken
            }
        })
            .then(function(response) {
                return response.json();
            })
            .then(function(data) {
                var modes = data.modes || [];
                var mode = modes.find(function(m) { return m.mode_slug === modeSlug; });

                if (!mode) {
                    showNotification('Error', 'Mode not found', 'error');
                    return;
                }

                // Populate all form fields
                document.getElementById('mode-slug').value = mode.mode_slug;
                document.getElementById('mode-display-name').value = mode.mode_display_name;
                document.getElementById('mode-min-price').value = mode.min_price || 0;
                document.getElementById('mode-currency').value = mode.currency || 'usd';
                document.getElementById('mode-description').value = mode.description || '';
                document.getElementById('mode-product-url').value = mode.product_url || '';
                document.getElementById('mode-sku').value = mode.sku || '';
                document.getElementById('mode-bulk-sku').value = mode.bulk_sku || '';

                // Handle expiration datetime
                if (mode.expiration_datetime) {
                    var date = new Date(mode.expiration_datetime);
                    var dateStr = date.toISOString().slice(0, 16);
                    document.getElementById('mode-expiration').value = dateStr;
                } else {
                    document.getElementById('mode-expiration').value = '';
                }

                openModal(true);
            })
            .catch(function(error) {
                showNotification('Error', 'Failed to load mode data: ' + error.message, 'error');
            });
    }

    function deleteMode(modeSlug) {
        openDeleteConfirm(modeSlug);
    }
    function openDeleteConfirm(modeSlug) {
        pendingDeleteModeSlug = modeSlug;
        var label = document.getElementById('confirm-delete-mode');
        if (label) { label.textContent = modeSlug; }
        var modal = document.getElementById('confirm-delete-modal');
        if (modal) { modal.style.display = 'block'; }
    }

    function closeDeleteConfirm() {
        var modal = document.getElementById('confirm-delete-modal');
        if (modal) { modal.style.display = 'none'; }
        pendingDeleteModeSlug = null;
    }

    function confirmDelete() {
        if (!pendingDeleteModeSlug) { return; }
        var csrftoken = getCookie('csrftoken');
        fetch(courseModesUrl, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({
                mode_slug: pendingDeleteModeSlug
            })
        })
            .then(function(response) {
                if (response.ok) {
                    return response.json();
                } else {
                    return response.json().then(function(err) {
                        throw new Error(err.error || 'Failed to delete course mode');
                    });
                }
            })
            .then(function(result) {
                closeDeleteConfirm();
                showNotification('Mode Deleted', 'Course mode has been deleted successfully', 'success');
                setTimeout(function() { location.reload(); }, 1000);
            })
            .catch(function(error) {
                closeDeleteConfirm();
                showNotification('Error', error.message, 'error');
            });
    }

    // Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function() {
        // New course mode button
        var newButton = document.querySelector('.new-course-mode-button');
        if (newButton) {
            newButton.addEventListener('click', function(e) {
                e.preventDefault();
                openModal(false);
            });
        }

        // Close button
        var closeButton = document.querySelector('.modal-close');
        if (closeButton) {
            closeButton.addEventListener('click', function(e) {
                e.preventDefault();
                closeModal();
            });
        }

        // Cancel button
        var cancelButton = document.querySelector('.cancel-button');
        if (cancelButton) {
            cancelButton.addEventListener('click', function(e) {
                e.preventDefault();
                closeModal();
            });
        }

        // Save button
        var saveButton = document.querySelector('.save-button');
        if (saveButton) {
            saveButton.addEventListener('click', function(e) {
                e.preventDefault();
                saveMode();
            });
        }

        // Edit buttons
        var editButtons = document.querySelectorAll('.edit-mode-button');
        editButtons.forEach(function(button) {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                var modeSlug = this.getAttribute('data-mode-slug');
                editMode(modeSlug);
            });
        });

        // Delete buttons
        var deleteButtons = document.querySelectorAll('.delete-mode-button');
        deleteButtons.forEach(function(button) {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                var modeSlug = this.getAttribute('data-mode-slug');
                deleteMode(modeSlug);
            });
        });

        // Confirm Delete Modal events
        var confirmDeleteModal = document.getElementById('confirm-delete-modal');
        if (confirmDeleteModal) {
            var confirmDeleteClose = confirmDeleteModal.querySelector('.modal-close');
            if (confirmDeleteClose) {
                confirmDeleteClose.addEventListener('click', function(e) {
                    e.preventDefault();
                    closeDeleteConfirm();
                });
            }
            var confirmDeleteCancel = document.getElementById('confirm-delete-cancel');
            if (confirmDeleteCancel) {
                confirmDeleteCancel.addEventListener('click', function(e) {
                    e.preventDefault();
                    closeDeleteConfirm();
                });
            }
            var confirmDeleteBtn = document.getElementById('confirm-delete-button');
            if (confirmDeleteBtn) {
                confirmDeleteBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    confirmDelete();
                });
            }
        }

        // Mode slug change - auto-fill display name
        var modeSlugSelect = document.getElementById('mode-slug');
        if (modeSlugSelect) {
            modeSlugSelect.addEventListener('change', function() {
                if (!isEditMode) {
                    var displayNameInput = document.getElementById('mode-display-name');
                    var displayNames = {
                        audit: 'Audit',
                        verified: 'Verified Certificate',
                        honor: 'Honor Code Certificate',
                        professional: 'Professional Education',
                        'no-id-professional': 'Professional Education (No ID)',
                        credit: 'Credit',
                        masters: 'Masters'
                    };
                    if (displayNames[this.value]) {
                        displayNameInput.value = displayNames[this.value];
                    }
                }
            });
        }
    });
}());
