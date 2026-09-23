(function () {
    function getLayout() {
        var match = document.cookie.match(/(?:^|; )bustag_layout=([^;]*)/);
        var layout = match ? decodeURIComponent(match[1]) : '';
        return layout === 'single' || layout === 'double' ? layout : '';
    }

    function applyLayout() {
        var layout = getLayout();
        if (!layout || !document.body) return;
        document.body.classList.remove('layout-single', 'layout-double');
        document.body.classList.add('layout-' + layout);
        var button = document.querySelector('.layout-toggle');
        if (button) {
            var next = layout === 'double' ? 'single' : 'double';
            button.setAttribute('data-layout-target', next);
            button.textContent = next === 'single' ? '切单排' : '切双排';
        }
    }

    applyLayout();

    // Preserve the NAS's bounded next-page and cover prefetch improvement.
    function prefetchNextPage() {
        var links = Array.prototype.slice.call(document.querySelectorAll('a[href]'));
        var next = links.find(function (link) {
            return (link.textContent || '').replace(/\s+/g, '').indexOf('下一页') !== -1;
        });
        if (!next || !next.href || next.href === window.location.href) return;

        var key = 'bustag-prefetch:' + next.href;
        try {
            if (sessionStorage.getItem(key)) return;
            sessionStorage.setItem(key, 'loading');
        } catch (e) {}

        fetch(next.href, {credentials: 'same-origin', cache: 'force-cache'})
            .then(function (response) {
                if (!response.ok) throw new Error('prefetch page ' + response.status);
                return response.text();
            })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, 'text/html');
                var urls = Array.prototype.map.call(
                    doc.querySelectorAll('img.coverimg[src]'),
                    function (img) { return img.getAttribute('src'); }
                ).filter(function (url, index, all) {
                    return url && all.indexOf(url) === index;
                });
                var cursor = 0;
                function loadBatch() {
                    var batch = urls.slice(cursor, cursor + 2);
                    cursor += batch.length;
                    if (!batch.length) {
                        try { sessionStorage.setItem(key, 'done'); } catch (e) {}
                        return;
                    }
                    var remaining = batch.length;
                    batch.forEach(function (url) {
                        var image = new Image();
                        image.onload = image.onerror = function () {
                            remaining -= 1;
                            if (!remaining) window.setTimeout(loadBatch, 150);
                        };
                        image.src = new URL(url, next.href).href;
                    });
                }
                loadBatch();
            })
            .catch(function () {
                try { sessionStorage.removeItem(key); } catch (e) {}
            });
    }

    $(function () {
    function actorStateLabel(state) {
        return state === 'like' ? '喜欢' : (state === 'dislike' ? '不喜欢' : '待确认');
    }

    function applyActorState(actorId, state) {
        Array.prototype.forEach.call(document.querySelectorAll('.v2-actor-row[data-actor-id]'), function (form) {
            if (form.getAttribute('data-actor-id') !== actorId) return;
            Array.prototype.forEach.call(form.querySelectorAll('button[name="state"]'), function (button) {
                var selected = button.value === state;
                button.classList.toggle('active', selected);
                button.setAttribute('aria-pressed', selected ? 'true' : 'false');
            });
            form.setAttribute('data-saved-state', state);
        });
        Array.prototype.forEach.call(document.querySelectorAll('.actor-state-badge[data-actor-id]'), function (badge) {
            if (badge.getAttribute('data-actor-id') !== actorId) return;
            badge.classList.remove('badge-warning', 'badge-secondary', 'badge-danger');
            badge.classList.add(state === 'like' ? 'badge-warning' :
                (state === 'dislike' ? 'badge-danger' : 'badge-secondary'));
            badge.setAttribute('data-actor-state', state);
            badge.setAttribute('title', '演员偏好：' + actorStateLabel(state));
            badge.setAttribute('aria-label', badge.textContent.trim() + '，演员偏好：' + actorStateLabel(state));
        });
    }

    $(document).on('click', '.v2-actor-row button[name="state"]', function () {
        this.form.setAttribute('data-requested-state', this.value);
    });

    $(document).on('submit', '.v2-actor-row', function (event) {
        var form = this;
        var submitter = event.originalEvent && event.originalEvent.submitter;
        var state = submitter && submitter.name === 'state' ? submitter.value :
            form.getAttribute('data-requested-state');
        form.removeAttribute('data-requested-state');
        if (!state || !window.fetch || !window.FormData) return;
        event.preventDefault();
        if (form.getAttribute('data-saving') === 'true') return;
        form.setAttribute('data-saving', 'true');
        var buttons = form.querySelectorAll('button[name="state"]');
        Array.prototype.forEach.call(buttons, function (button) { button.disabled = true; });
        var status = form.querySelector('.v2-actor-save-status');
        if (status) {
            status.classList.remove('text-success', 'text-danger');
            status.classList.add('text-muted');
            status.textContent = '保存中…';
        }
        var data = new FormData(form);
        data.append('state', state);
        fetch(form.action, {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
            headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
            body: data
        }).then(function (response) {
            return response.json().then(function (result) {
                if (!response.ok || !result.ok) throw new Error('Actor preference save failed');
                return result;
            });
        }).then(function (result) {
            applyActorState(result.actor_id, result.state);
            if (status) {
                status.classList.remove('text-muted', 'text-danger');
                status.classList.add('text-success');
                status.textContent = '已保存';
            }
        }).catch(function () {
            if (status) {
                status.classList.remove('text-muted', 'text-success');
                status.classList.add('text-danger');
                status.textContent = '保存失败，请重试';
            }
        }).then(function () {
            form.removeAttribute('data-saving');
            Array.prototype.forEach.call(buttons, function (button) { button.disabled = false; });
        });
    });

    $('.layout-toggle').on('click', function (event) {
        event.preventDefault();
        var layout = $(this).attr('data-layout-target');
        if (layout !== 'single' && layout !== 'double') {
            return;
        }
        document.cookie = 'bustag_layout=' + layout + '; path=/; max-age=31536000; samesite=lax';
        // Reload the current URL so an external port (for example :1023) is
        // preserved by the browser instead of being rebuilt by the server.
        window.location.reload();
    });

    $('.coverimg').on('click', function () {
        $('#imglarge').attr('src', $(this).attr('src'));
        $('#imagemodal').modal('show');
    });

    $('#pagenav').on('change', function () {
        window.location = $(this).val();
    });

    // Preserve arrow-key pagination while leaving form controls untouched.
    $(document).on('keydown', function (event) {
        var target = event.target;
        var tag = target && target.tagName ? target.tagName.toLowerCase() : '';
        if (tag === 'input' || tag === 'textarea' || tag === 'select' ||
            (target && target.isContentEditable)) {
            return;
        }
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
            return;
        }
        var wanted = event.key === 'ArrowLeft' ? '上一页' :
            (event.key === 'ArrowRight' ? '下一页' : '');
        if (!wanted) return;
        var link = Array.prototype.find.call(document.querySelectorAll('a[href]'), function (item) {
            return (item.textContent || '').replace(/\s+/g, '').indexOf(wanted) !== -1;
        });
        if (!link || !link.href) return;
        event.preventDefault();
        window.location.href = link.href;
    });

    if (window.fetch && window.DOMParser && window.sessionStorage) {
        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(prefetchNextPage, {timeout: 1200});
        } else {
            window.setTimeout(prefetchNextPage, 500);
        }
    }
    });
})();
