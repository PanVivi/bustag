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
