/*
 * ATTENTION: The "eval" devtool has been used (maybe by default in mode: "development").
 * This devtool is neither made for production nor for readable output files.
 * It uses "eval()" calls to create a separate source file in the browser devtools.
 * If you are trying to read the output file, select a different devtool (https://webpack.js.org/configuration/devtool/)
 * or disable the default devtool with "devtool: false".
 * If you are looking for production-ready output files, see mode: "production" (https://webpack.js.org/configuration/mode/).
 */
(function webpackUniversalModuleDefinition(root, factory) {
	if(typeof exports === 'object' && typeof module === 'object')
		module.exports = factory();
	else if(typeof define === 'function' && define.amd)
		define([], factory);
	else {
		var a = factory();
		for(var i in a) (typeof exports === 'object' ? exports : root)[i] = a[i];
	}
})(self, function() {
return /******/ (function() { // webpackBootstrap
/******/ 	var __webpack_modules__ = ({

/***/ "./libs/select2/i18n/fa.js":
/*!*********************************!*\
  !*** ./libs/select2/i18n/fa.js ***!
  \*********************************/
/***/ (function() {

eval("/*! Select2 4.0.13 | https://github.com/select2/select2/blob/master/LICENSE.md */\n\n!function () {\n  if (jQuery && jQuery.fn && jQuery.fn.select2 && jQuery.fn.select2.amd) var n = jQuery.fn.select2.amd;\n  n.define(\"select2/i18n/fa\", [], function () {\n    return {\n      errorLoading: function errorLoading() {\n        return \"امکان بارگذاری نتایج وجود ندارد.\";\n      },\n      inputTooLong: function inputTooLong(n) {\n        return \"لطفاً \" + (n.input.length - n.maximum) + \" کاراکتر را حذف نمایید\";\n      },\n      inputTooShort: function inputTooShort(n) {\n        return \"لطفاً تعداد \" + (n.minimum - n.input.length) + \" کاراکتر یا بیشتر وارد نمایید\";\n      },\n      loadingMore: function loadingMore() {\n        return \"در حال بارگذاری نتایج بیشتر...\";\n      },\n      maximumSelected: function maximumSelected(n) {\n        return \"شما تنها می‌توانید \" + n.maximum + \" آیتم را انتخاب نمایید\";\n      },\n      noResults: function noResults() {\n        return \"هیچ نتیجه‌ای یافت نشد\";\n      },\n      searching: function searching() {\n        return \"در حال جستجو...\";\n      },\n      removeAllItems: function removeAllItems() {\n        return \"همه موارد را حذف کنید\";\n      }\n    };\n  }), n.define, n.require;\n}();\n\n//# sourceURL=webpack://Vuexy/./libs/select2/i18n/fa.js?");

/***/ })

/******/ 	});
/************************************************************************/
/******/ 	
/******/ 	// startup
/******/ 	// Load entry module and return exports
/******/ 	// This entry module can't be inlined because the eval devtool is used.
/******/ 	var __webpack_exports__ = {};
/******/ 	__webpack_modules__["./libs/select2/i18n/fa.js"]();
/******/ 	
/******/ 	return __webpack_exports__;
/******/ })()
;
});