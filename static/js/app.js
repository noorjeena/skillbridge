(() => {
    const toggle = document.querySelector('[data-menu-toggle]');
    const close = document.querySelector('[data-menu-close]');

    if (!toggle || !close) {
        return;
    }

    const setMenuOpen = (isOpen) => {
        document.body.classList.toggle('nav-open', isOpen);
        toggle.setAttribute('aria-expanded', String(isOpen));
        toggle.setAttribute('aria-label', isOpen ? 'Close navigation menu' : 'Open navigation menu');
    };

    toggle.addEventListener('click', () => {
        setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    close.addEventListener('click', () => setMenuOpen(false));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            setMenuOpen(false);
        }
    });
})();

(() => {
    const header = document.querySelector('.public-header');
    const toggle = document.querySelector('[data-home-menu-toggle]');
    const navigation = document.querySelector('#home-navigation');

    if (!header || !toggle || !navigation) {
        return;
    }

    const setMenuOpen = (isOpen) => {
        header.classList.toggle('home-nav-open', isOpen);
        toggle.setAttribute('aria-expanded', String(isOpen));
        toggle.setAttribute('aria-label', isOpen ? 'Close home navigation' : 'Open home navigation');
    };

    toggle.addEventListener('click', () => {
        setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });

    navigation.addEventListener('click', (event) => {
        if (event.target instanceof Element && event.target.closest('a')) {
            setMenuOpen(false);
        }
    });

    document.addEventListener('click', (event) => {
        if (event.target instanceof Node && !header.contains(event.target)) {
            setMenuOpen(false);
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            setMenuOpen(false);
            toggle.focus();
        }
    });

    const updateHeader = () => {
        header.classList.toggle('home-header-scrolled', window.scrollY > 12);
    };

    updateHeader();
    window.addEventListener('scroll', updateHeader, { passive: true });

    const revealItems = document.querySelectorAll('.home-reveal');
    if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    const observer = new IntersectionObserver((entries, currentObserver) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add('home-reveal-visible');
                entry.target.classList.remove('home-reveal-pending');
                currentObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.12 });

    revealItems.forEach((item) => {
        item.classList.add('home-reveal-pending');
        observer.observe(item);
    });
})();
