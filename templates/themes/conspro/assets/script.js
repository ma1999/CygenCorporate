(function($) {
    'use strict';

    // ==================== Preloader ====================
    function hidePreloader() {
        $('.preloader').length && $('.preloader').delay(200).fadeOut(500);
    }

    // ==================== Header Style (Fixed Header) ====================
    function headerStyle() {
        if ($('.main-header').length) {
            var scrollPos = $(window).scrollTop(),
                header = $('.main-header'),
                scrollToTop = $('.scroll-to-top');

            if (scrollPos >= 250) {
                header.addClass('fixed-header');
                scrollToTop.fadeIn(300);
            } else {
                header.removeClass('fixed-header');
                scrollToTop.fadeOut(300);
            }
        }
    }

    headerStyle();

    // ==================== Domain Check (License) ====================
    // if (window.location.hostname != 'v3dboy.ir') {
    //     alert('لطفا قالب را خریداری نمایید');
    //     window.location.replace('https://www.rtl-theme.com/?p=164985');
    // }

    // ==================== Dropdown Navigation ====================
    if ($('.main-header li.dropdown ul').length) {
        // Add dropdown button
        $('.main-header li.dropdown').append(
            '<div class="dropdown-btn"><span class="fa fa-angle-down"></span></div>'
        );

        // Toggle dropdown on button click (mobile)
        $('.main-header li.dropdown .dropdown-btn').on('click', function() {
            $(this).prev('ul').slideToggle(500);
        });

        // Prevent default on navigation links
        $('.navigation li.dropdown > a').on('click', function(e) {
            e.preventDefault();
        });
    }

    // ==================== Counter Animation ====================
    if ($('.count-box').length) {
        $('.count-box').appear(function() {
            var $this = $(this),
                countText = $this.find('.count-text').attr('data-stop'),
                countNum = parseInt($this.find('.count-text').attr('data-speed'), 10);

            if (!$this.hasClass('counted')) {
                $this.addClass('counted');
                $({ countNum: parseInt($this.find('.count-text').text()) })
                    .animate({ countNum: countText }, {
                        duration: countNum,
                        easing: 'linear',
                        step: function() {
                            $this.find('.count-text').text(Math.floor(this.countNum));
                        },
                        complete: function() {
                            $this.find('.count-text').text(this.countNum);
                        }
                    });
            }
        }, { accY: 0 });
    }

    // ==================== MixItUp (Filter) ====================
    $('.filter-list').length && $('.filter-list').mixItUp({});

    // ==================== Two Item Carousel ====================
    if ($('.two-item-carousel').length) {
        $('.two-item-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 50,
            nav: true,
            smartSpeed: 700,
            autoplay: 5000,
            navText: [
                '<span class="fa fa-angle-right"></span>',
                '<span class="fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                600:    { items: 1 },
                800:    { items: 2 },
                1024:   { items: 2 },
                1200:   { items: 2 }
            }
        });
    }

    // ==================== Three Item Carousel ====================
    if ($('.three-item-carousel').length) {
        $('.three-item-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 50,
            nav: true,
            smartSpeed: 700,
            autoplay: 5000,
            navText: [
                '<span class="fa fa-angle-right"></span>',
                '<span class="fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                300:    { items: 1 },
                600:    { items: 2 },
                800:    { items: 2 },
                1024:   { items: 3, margin: 30 },
                1200:   { items: 3 }
            }
        });
    }

    // ==================== Four Item Carousel ====================
    if ($('.four-item-carousel').length) {
        $('.four-item-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 0,
            nav: true,
            smartSpeed: 700,
            autoplay: 5000,
            navText: [
                '<span class="fa fa-angle-right"></span>',
                '<span class="fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                600:    { items: 2 },
                800:    { items: 3 },
                1024:   { items: 4 },
                1200:   { items: 4 }
            }
        });
    }

    // ==================== Sponsors Carousel ====================
    if ($('.sponsors-carousel').length) {
        $('.sponsors-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 20,
            nav: true,
            smartSpeed: 500,
            autoplay: 4000,
            navText: [
                '<span class="icon fa fa-angle-right"></span>',
                '<span class="icon fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                480:    { items: 2 },
                600:    { items: 3 },
                800:    { items: 4 },
                1024:   { items: 5 }
            }
        });
    }

    // ==================== Single Item Carousel ====================
    if ($('.single-item-carousel').length) {
        $('.single-item-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 10,
            nav: true,
            smartSpeed: 1000,
            autoplay: 5000,
            navText: [
                '<span class="fa fa-angle-right"></span>',
                '<span class="fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                600:    { items: 1 },
                1200:   { items: 1 }
            }
        });
    }

    // ==================== Price Range Slider ====================
    if ($('.price-range-slider').length) {
        $('.price-range-slider').slider({
            range: true,
            min: 0,
            max: 1000000,
            values: [10000, 500000],
            slide: function(event, ui) {
                $('input.property-amount').val(
                    ui.values[1] + ' تومان - ' + ui.values[0] + ' تومان'
                );
            }
        });

        $('input.property-amount').val(
            $('.price-range-slider').slider('values', 1) + ' تومان - ' +
            $('.price-range-slider').slider('values', 0) + ' تومان'
        );
    }

    // ==================== Project Carousel ====================
    if ($('.project-carousel').length) {
        $('.project-carousel').owlCarousel({
            loop: true,
            rtl: true,
            margin: 30,
            nav: true,
            smartSpeed: 700,
            autoplay: 5000,
            navText: [
                '<span class="icon fa fa-angle-right"></span>',
                '<span class="icon fa fa-angle-left"></span>'
            ],
            responsive: {
                0:      { items: 1 },
                600:    { items: 2 },
                800:    { items: 2 },
                1024:   { items: 3 },
                1200:   { items: 4 },
                1400:   { items: 4 },
                1600:   { items: 4 }
            }
        });
    }

    // ==================== Project Tabs ====================
    if ($('.project-tab').length) {
        $('.project-tab .product-tab-btns .p-tab-btn').on('click', function(e) {
            e.preventDefault();
            var target = $($(this).attr('data-tab'));

            if ($(target).hasClass('active-tab')) {
                return false;
            } else {
                // Remove active from all buttons
                $('.project-tab .product-tab-btns .p-tab-btn').removeClass('active-btn');
                $(this).addClass('active-btn');

                // Remove active from all tabs
                $('.project-tab .p-tabs-content .p-tab').removeClass('active-tab');
                $(target).addClass('active-tab');
            }
        });
    }

    // ==================== Tabs Box ====================
    if ($('.tabs-box').length) {
        $('.tabs-box .tab-buttons .tab-btn').on('click', function(e) {
            e.preventDefault();
            var target = $($(this).attr('data-tab'));

            if ($(target).is(':visible')) {
                return false;
            } else {
                // Remove active from all buttons
                target.parents('.tabs-box')
                    .find('.tab-buttons')
                    .find('.tab-btn')
                    .removeClass('active-btn');
                $(this).addClass('active-btn');

                // Hide all tabs
                target.parents('.tabs-box')
                    .find('.tabs-content')
                    .find('.tab')
                    .fadeOut(0);
                target.parents('.tabs-box')
                    .find('.tabs-content')
                    .find('.tab')
                    .removeClass('active-tab');

                // Show selected tab
                $(target).fadeIn(300);
                $(target).addClass('active-tab');
            }
        });
    }

    // ==================== Shop Page Synced Carousels ====================
    if ($('.shop-page .image-carousel').length && $('.shop-page .thumbs-carousel').length) {
        var sync1 = $('.shop-page .image-carousel'),
            sync2 = $('.shop-page .thumbs-carousel'),
            flag = false,
            duration = 500;

        // Main image carousel
        sync1.owlCarousel({
            loop: true,
            rtl: true,
            items: 1,
            margin: 0,
            nav: false,
            navText: [
                '<span class="icon fa fa-angle-left"></span>',
                '<span class="icon fa fa-angle-right"></span>'
            ],
            dots: false,
            autoplay: true,
            autoplayTimeout: 5000
        }).on('changed.owl.carousel', function(e) {
            if (!flag) {
                flag = false;
                sync2.trigger('to.owl.carousel', [e.item.index, duration, true]);
                flag = false;
            }
        });

        // Thumbnail carousel
        sync2.owlCarousel({
            loop: true,
            rtl: true,
            margin: 10,
            items: 1,
            nav: true,
            navText: [
                '<span class="icon fa fa-angle-left"></span>',
                '<span class="icon fa fa-angle-right"></span>'
            ],
            dots: false,
            center: false,
            autoplay: true,
            autoplayTimeout: 5000,
            responsive: {
                0:      { items: 2, autoWidth: false },
                400:    { items: 3, autoWidth: false },
                600:    { items: 4, autoWidth: false },
                900:    { items: 5, autoWidth: false },
                1000:   { items: 4, autoWidth: false }
            }
        }).on('click', '.owl-item', function() {
            sync1.trigger('to.owl.carousel', [$(this).index(), duration, true]);
        }).on('changed.owl.carousel', function(e) {
            if (!flag) {
                flag = true;
                sync1.trigger('to.owl.carousel', [e.item.index, duration, true]);
                flag = false;
            }
        });
    }

    // ==================== Quantity Spinner (TouchSpin) ====================
    if ($('.quantity-spinner').length) {
        $('input.quantity-spinner').TouchSpin({
            verticalbuttons: true
        });
    }

    // ==================== Lightbox / Fancybox ====================
    if ($('.lightbox-image').length) {
        $('.lightbox-image').fancybox({
            openEffect: 'fade',
            closeEffect: 'fade',
            helpers: {
                media: {}
            }
        });
    }

    // ==================== Contact Form Validation ====================
    if ($('#contact-form').length) {
        // Persian validation messages
        $.extend($.validator.messages, {
            required: "تکمیل این فیلد اجباری است.",
            remote: "لطفا این فیلد را تصحیح کنید.",
            email: "لطفا یک ایمیل صحیح وارد کنید.",
            url: "لطفا آدرس صحیح وارد کنید.",
            date: "لطفا تاریخ صحیح وارد کنید.",
            dateFA: "لطفا یک تاریخ صحیح وارد کنید.",
            dateISO: "لطفا تاریخ صحیح وارد کنید (ISO).",
            number: "لطفا عدد صحیح وارد کنید.",
            digits: "لطفا تنها رقم وارد کنید.",
            creditcard: "لطفا کریدیت کارت صحیح وارد کنید.",
            equalTo: "لطفا مقدار برابری وارد کنید.",
            extension: "لطفا مقدار وارد کنید که",
            alphanumeric: "لطفا مقدار را عدد (انگلیسی) وارد کنید.",
            maxlength: $.validator.format("لطفا بیشتر از {0} حرف وارد نکنید."),
            minlength: $.validator.format("لطفا کمتر از {0} حرف وارد نکنید."),
            rangelength: $.validator.format("لطفا مقداری بین {0} تا {1} حرف وارد کنید."),
            range: $.validator.format("لطفا مقداری بین {0} تا {1} وارد کنید."),
            max: $.validator.format("لطفا مقداری کمتر از {0} وارد کنید."),
            min: $.validator.format("لطفا مقداری بیشتر از {0} وارد کنید."),
            minWords: $.validator.format("لطفا حداقل {0} کلمه وارد کنید."),
            maxWords: $.validator.format("لطفا حداکثر {0} کلمه وارد کنید.")
        });

        // Form validation rules
        $('#contact-form').validate({
            rules: {
                username: { required: true },
                email: { required: true, email: true },
                subject: { required: true },
                message: { required: true }
            }
        });
    }

    // ==================== Scroll to Target ====================
    if ($('.scroll-to-target').length) {
        $('.scroll-to-target').on('click', function() {
            var target = $(this).attr('data-target');
            $('html, body').animate({
                scrollTop: $(target).offset().top
            }, 1000);
        });
    }

    // ==================== WOW.js Animations ====================
    if ($('.wow').length) {
        var wow = new WOW({
            boxClass: 'wow',
            animateClass: 'animated',
            offset: 0,
            mobile: false,
            live: true
        });
        wow.init();
    }

    // ==================== Window Events ====================
    $(window).on('scroll', function() {
        headerStyle();
    });

    $(window).on('load', function() {
        hidePreloader();
    });

    // ==================== HTML5 Input Validation (Persian) ====================
    // Required fields
    $('input[required], textarea[required]').on('invalid', function() {
        this.setCustomValidity('وارد کردن این قسمت الزامی است');
    });

    // Email fields
    $('input[type="email"]').on('invalid', function() {
        if (this.validity.typeMismatch) {
            this.setCustomValidity('لطفا یک ایمیل معتبر وارد نمایید');
        }
    });

    // Clear custom message on input
    $('input[required], textarea[required], input[type="email"]').on('input', function() {
        this.setCustomValidity('');
    });

})(window.jQuery);