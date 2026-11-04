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

/***/ "./libs/bootstrap-select/i18n/defaults-fa_IR.js":
/*!******************************************************!*\
  !*** ./libs/bootstrap-select/i18n/defaults-fa_IR.js ***!
  \******************************************************/
/***/ (function() {

eval("/*\n * Translated default messages for bootstrap-select.\n * Locale: FA (Farsi)\n * Region: IR (Iran)\n */\n(function ($) {\n  $.fn.selectpicker.defaults = {\n    noneSelectedText: 'موردی انتخاب نشده است',\n    noneResultsText: 'هیج مشابهی برای {0} پیدا نشد',\n    countSelectedText: '{0} از {1} مورد انتخاب شده',\n    maxOptionsText: ['بیشتر ممکن نیست (حداکثر {n} مورد)', 'بیشتر ممکن نیست (حداکثر {n} مورد)'],\n    selectAllText: 'انتخاب همه',\n    deselectAllText: 'انتخاب هیچ‌کدام',\n    multipleSeparator: ' ، '\n  };\n})(jQuery);\n\n//# sourceURL=webpack://Vuexy/./libs/bootstrap-select/i18n/defaults-fa_IR.js?");

/***/ })

/******/ 	});
/************************************************************************/
/******/ 	
/******/ 	// startup
/******/ 	// Load entry module and return exports
/******/ 	// This entry module can't be inlined because the eval devtool is used.
/******/ 	var __webpack_exports__ = {};
/******/ 	__webpack_modules__["./libs/bootstrap-select/i18n/defaults-fa_IR.js"]();
/******/ 	
/******/ 	return __webpack_exports__;
/******/ })()
;
});