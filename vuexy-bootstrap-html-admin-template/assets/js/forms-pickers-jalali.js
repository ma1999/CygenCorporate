/**
 * Form Picker
 */

'use strict';

// Flat Picker
(function () {

    //flatpickr.l10ns.default.firstDayOfWeek = 6;

    // Flat Picker
    // --------------------------------------------------------------------
    const flatpickrDate = document.querySelector('#flatpickr-date'),
        flatpickrTime = document.querySelector('#flatpickr-time'),
        flatpickrDateTime = document.querySelector('#flatpickr-datetime'),
        flatpickrMulti = document.querySelector('#flatpickr-multi'),
        flatpickrRange = document.querySelector('#flatpickr-range'),
        flatpickrInline = document.querySelector('#flatpickr-inline'),
        flatpickrFriendly = document.querySelector('#flatpickr-human-friendly'),
        flatpickrDisabledRange = document.querySelector('#flatpickr-disabled-range');

    // Date
    if (flatpickrDate) {
        flatpickrDate.flatpickr({
            disableMobile: "true",
            monthSelectorType: 'static',
            locale: 'fa',
            altFormat: 'Y/m/d',
        });
    }

    // Time
    if (flatpickrTime) {
        flatpickrTime.flatpickr({
            disableMobile: "true",
            enableTime: true,
            noCalendar: true,
            locale: 'fa',
            altInput: true,
            altFormat: 'H:i',
        });
    }

    // Datetime
    if (flatpickrDateTime) {
        flatpickrDateTime.flatpickr({
            disableMobile: "true",
            enableTime: true,
            dateFormat: 'Y/m/d H:i',
            locale: 'fa',
        });
    }

    // Multi Date Select
    if (flatpickrMulti) {
        flatpickrMulti.flatpickr({
            disableMobile: "true",
            weekNumbers: true,
            enableTime: true,
            locale: 'fa',
            mode: 'multiple',
            dateFormat: 'Y/m/d H:i',
            minDate: 'today'
        });
    }

    // Range
    if (typeof flatpickrRange != undefined) {
        flatpickrRange.flatpickr({
            disableMobile: "true",
            mode: 'range',
            locale: 'fa',
            dateFormat: 'Y/m/d',
        });
    }

    // Inline
    if (flatpickrInline) {
        flatpickrInline.flatpickr({
            disableMobile: "true",
            inline: true,
            allowInput: false,
            dateFormat: 'Y/m/d',
            monthSelectorType: 'static',
            locale: 'fa',
        });
    }

    // Human Friendly
    if (flatpickrFriendly) {
        flatpickrFriendly.flatpickr({
            disableMobile: "true",
            altInput: true,
            altFormat: 'j F Y',
            dateFormat: 'Y/m/d',
            locale: 'fa',
        });
    }

    // Disabled Date Range
    if (flatpickrDisabledRange) {
        const fromDate = new JDate(JDate.now() - 3600 * 1000 * 48);
        const toDate = new JDate(JDate.now() + 3600 * 1000 * 48);

        flatpickrDisabledRange.flatpickr({
            disableMobile: "true",
            dateFormat: 'Y/m/d',
            locale: 'fa',
            disable: [
                {
                    from: fromDate.toISOString().split('T')[0],
                    to: toDate.toISOString().split('T')[0]
                }
            ]
        });
    }
})();

// Jalali Date Picker
//document : https://github.com/majidh1/JalaliDatePicker

(function () {

    // Jalali Date Picker
    // --------------------------------------------------------------------

    jalaliDatepicker.startWatch({
        minDate: "attr",
        maxDate: "attr",
        minTime: "attr",
        maxTime: "attr",
        hideAfterChange: false,
        autoHide: true,
        showTodayBtn: true,
        showEmptyBtn: true,
        topSpace: 10,
        bottomSpace: 30,
        time: true,
        dayRendering(opt, input) {
            return {
                isHollyDay: opt.day == 1
            }
        }
    });

    document.getElementById("jalali-picker-date-button").onclick  = function(e){
        e.stopImmediatePropagation();
        jalaliDatepicker.show(document.getElementById("jalali-picker-date-button"));
    };

    document.getElementById("jalali-picker-date-button-input").onclick  = function(e){
        e.stopImmediatePropagation();
        jalaliDatepicker.show(document.getElementById("jalali-picker-date-input-disable"));
    };

    document.getElementById("jalali-picker-date-button-hide").onclick  = function(e){
        e.stopImmediatePropagation();
        jalaliDatepicker.hide();
    };


})();


/*
$.fn.datepicker.dates['fa'] = {
    days: ["یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه"],
    daysShort: ["یک", "دو", "سه", "چهار", "پنج", "جمعه", "شنبه"],
    daysMin: ["ی", "د", "س", "چ", "پ", "ج", "ش"],
    months: ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"],
    monthsShort: ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"],
    today: "امروز",
    clear: "پاک کردن",
    titleFormat: "MM yyyy",
    weekStart: 6
};
*/

// * Pickers with jQuery dependency (jquery)
$(function () {
    // Bootstrap Datepicker
    //document: https://github.com/mzangeneh/bootstrap-datepicker-shamsi/
    // --------------------------------------------------------------------

    var bsDatepickerBasic = $('#bs-datepicker-basic'),
        bsDatepickerFormat = $('#bs-datepicker-format'),
        bsDatepickerRange = $('#bs-datepicker-daterange'),
        bsDatepickerDisabledDays = $('#bs-datepicker-disabled-days'),
        bsDatepickerMultidate = $('#bs-datepicker-multidate'),
        bsDatepickerOptions = $('#bs-datepicker-options'),
        bsDatepickerAutoclose = $('#bs-datepicker-autoclose'),
        bsDatepickerInlinedate = $('#bs-datepicker-inline');

    // Basic
    if (bsDatepickerBasic.length) {
        bsDatepickerBasic.datepicker({
            language: 'fa',
            format: 'yyyy/mm/dd',
            todayHighlight: true,
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Format
    if (bsDatepickerFormat.length) {
        bsDatepickerFormat.datepicker({
            language: 'fa',
            todayHighlight: true,
            format: 'yyyy/mm/dd',
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Range
    if (bsDatepickerRange.length) {
        bsDatepickerRange.datepicker({
            language: 'fa',
            format: 'yyyy/mm/dd',
            todayHighlight: true,
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Disabled Days
    if (bsDatepickerDisabledDays.length) {
        bsDatepickerDisabledDays.datepicker({
            language: 'fa',
            format: 'yyyy/mm/dd',
            todayHighlight: true,
            daysOfWeekDisabled: [0, 6],
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Multiple
    if (bsDatepickerMultidate.length) {
        bsDatepickerMultidate.datepicker({
            language: 'fa',
            format: 'yyyy/mm/dd',
            multidate: true,
            todayHighlight: true,
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Options
    if (bsDatepickerOptions.length) {
        bsDatepickerOptions.datepicker({
            language: 'fa',
            format: 'yyyy/mm/dd',
            calendarWeeks: true,
            clearBtn: true,
            todayHighlight: true,
            orientation: isRtl ? 'auto left' : 'auto right'
        });
    }

    // Auto close
    if (bsDatepickerAutoclose.length) {
        bsDatepickerAutoclose.datepicker({
            format: 'yyyy/mm/dd',
            language: 'fa',
            todayHighlight: true,
            autoclose: true,
            orientation: isRtl ? 'auto right' : 'auto left'
        });
    }

    // Inline picker
    if (bsDatepickerInlinedate.length) {
        bsDatepickerInlinedate.datepicker({
            format: 'yyyy/mm/dd',
            language: 'fa',
            todayHighlight: true
        });
    }

    // Bootstrap Daterange Picker
    // --------------------------------------------------------------------


    var dateRangePickerFa = {
        "format": "jYYYY/jMM/jDD",
        "separator": " - ",
        "applyLabel": "اعمال",
        "cancelLabel": "انصراف",
        "startLabel": 'تاریخ شروع',
        "endLabel": 'تاریخ پایان',
        "fromLabel": "از",
        "toLabel": "تا",
        "weekLabel": "هفته",
        "customRangeLabel": "انتخاب بازه",
        "daysOfWeek": ["ی", "د", "س", "چ", "پ", "ج", "ش"],
        "monthNames": ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"],
        "firstDay": 6
    };

    var dateRangePickerTimeFa = {
        "format": "jYYYY/jMM/jDD h:mm A",
        "separator": " - ",
        "applyLabel": "اعمال",
        "cancelLabel": "انصراف",
        "startLabel": 'تاریخ شروع',
        "endLabel": 'تاریخ پایان',
        "fromLabel": "از",
        "toLabel": "تا",
        "weekLabel": "هفته",
        "customRangeLabel": "انتخاب بازه",
        "daysOfWeek": ["ی", "د", "س", "چ", "پ", "ج", "ش"],
        "monthNames": ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"],
        "firstDay": 6
    };

    var bsRangePickerBasic = $('#bs-rangepicker-basic'),
        bsRangePickerSingle = $('#bs-rangepicker-single'),
        bsRangePickerTime = $('#bs-rangepicker-time'),
        bsRangePickerRange = $('#bs-rangepicker-range'),
        bsRangePickerWeekNum = $('#bs-rangepicker-week-num'),
        bsRangePickerDropdown = $('#bs-rangepicker-dropdown'),
        bsRangePickerCancelBtn = document.getElementsByClassName('cancelBtn');

    // Basic
    if (bsRangePickerBasic.length) {
        bsRangePickerBasic.daterangepicker({
            locale: dateRangePickerFa,
            opens: isRtl ? 'left' : 'right'
        });
    }

    // Single
    if (bsRangePickerSingle.length) {
        bsRangePickerSingle.daterangepicker({
            locale: dateRangePickerFa,
            singleDatePicker: true,
            opens: isRtl ? 'left' : 'right'
        });
    }

    // Time & Date
    if (bsRangePickerTime.length) {
        bsRangePickerTime.daterangepicker({
            timePicker: true,
            timePickerIncrement: 30,
            locale: dateRangePickerTimeFa,
            opens: isRtl ? 'left' : 'right'
        });
    }

    if (bsRangePickerRange.length) {

        bsRangePickerRange.daterangepicker({
            locale: dateRangePickerFa,
            opens: isRtl ? 'left' : 'right'
        });

        const dropdownItems = document.querySelectorAll('#bs-rangepicker-range-drop .dropdown-item');

        let counter = 0;

        //document : https://github.com/jalaali/moment-jalaali

        dropdownItems.forEach(item => {

            switch (counter) {
                case 0:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment(),
                            endDate: moment(),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 1:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment().subtract(1, 'days'),
                            endDate: moment().subtract(1, 'days'),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 2:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment().subtract(6, 'days'),
                            endDate: moment(),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 3:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment().subtract(29, 'days'),
                            endDate: moment(),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 4:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment().startOf('jMonth'),
                            endDate: moment().endOf('jMonth'),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 5:
                    item.addEventListener('click', function() {
                        bsRangePickerRange.daterangepicker({
                            startDate: moment().subtract(1, 'month').startOf('jMonth'),
                            endDate: moment().subtract(1, 'month').endOf('jMonth'),
                            locale: dateRangePickerFa,
                        });
                    });
                    break;
                case 6:
                    item.addEventListener('click', function() {
                        $('#bs-rangepicker-range').focus();
                    });
                    break;
            }

            counter++;

        });

    }

    // Week Numbers
    if (bsRangePickerWeekNum.length) {
        bsRangePickerWeekNum.daterangepicker({
            locale: dateRangePickerFa,
            showWeekNumbers: true,
            opens: isRtl ? 'left' : 'right'
        });
    }
    // Dropdown
    if (bsRangePickerDropdown.length) {
        bsRangePickerDropdown.daterangepicker({
            locale: dateRangePickerFa,
            showDropdowns: true,
            opens: isRtl ? 'left' : 'right'
        });
    }

    // Adding btn-label-secondary class in cancel btn
    for (var i = 0; i < bsRangePickerCancelBtn.length; i++) {
        bsRangePickerCancelBtn[i].classList.remove('btn-default');
        bsRangePickerCancelBtn[i].classList.add('btn-label-primary');
    }

    // jQuery Timepicker
    // --------------------------------------------------------------------

    var timePickerLocaleFa = {
        am: ' ق.ظ',
        pm: ' ب.ظ',
        AM: ' ق.ظ',
        PM: ' ب.ظ',
        decimal: '.',
        mins: 'دقیقه',
        hr: 'ساعت',
        hrs: 'ساعت'
    };

    var basicTimepicker = $('#timepicker-basic'),
      minMaxTimepicker = $('#timepicker-min-max'),
      disabledTimepicker = $('#timepicker-disabled-times'),
      formatTimepicker = $('#timepicker-format'),
      stepTimepicker = $('#timepicker-step'),
      altHourTimepicker = $('#timepicker-24hours');

    // Basic
    if (basicTimepicker.length) {
        basicTimepicker.timepicker({
            lang: timePickerLocaleFa,
            orientation: isRtl ? 'r' : 'l'
        });
    }

    // Min & Max
    if (minMaxTimepicker.length) {
        minMaxTimepicker.timepicker({
            lang: timePickerLocaleFa,
            minTime: '2:00pm',
            maxTime: '7:00pm',
            showDuration: true,
            orientation: isRtl ? 'r' : 'l'
        });
    }

    // Disabled Picker
    if (disabledTimepicker.length) {
        disabledTimepicker.timepicker({
            lang: timePickerLocaleFa,
            disableTimeRanges: [
                ['12am', '3am'],
                ['4am', '4:30am']
            ],
            orientation: isRtl ? 'r' : 'l'
        });
    }

    // Format Picker
    if (formatTimepicker.length) {
        formatTimepicker.timepicker({
            lang: timePickerLocaleFa,
            timeFormat: 'H:i:s',
            orientation: isRtl ? 'r' : 'l'
        });
    }

    // Steps Picker
    if (stepTimepicker.length) {
        stepTimepicker.timepicker({
            lang: timePickerLocaleFa,
            step: 15,
            orientation: isRtl ? 'r' : 'l'
        });
    }

    // 24 Hours Format
    if (altHourTimepicker.length) {
        altHourTimepicker.timepicker({
            lang: timePickerLocaleFa,
            show: '24:00',
            timeFormat: 'H:i:s',
            orientation: isRtl ? 'r' : 'l'
        });
    }
});