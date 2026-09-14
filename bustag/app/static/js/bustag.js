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
    });
})();
