(function () {
  "use strict";

  function formatMB(size) {
    return (size / (1024 * 1024)).toFixed(1);
  }

  function setWarning(input, message) {
    var row = input.closest(".form-row") || input.parentNode;
    var warning = row.querySelector(".wp-upload-warning");
    if (!warning) {
      warning = document.createElement("div");
      warning.className = "wp-upload-warning";
      row.appendChild(warning);
    }
    warning.textContent = message;
    input.setAttribute("aria-invalid", "true");
  }

  function clearWarning(input) {
    var row = input.closest(".form-row") || input.parentNode;
    var warning = row.querySelector(".wp-upload-warning");
    if (warning) {
      warning.textContent = "";
    }
    input.removeAttribute("aria-invalid");
  }

  function validate(input) {
    var maxSize = Number(input.dataset.maxSize || 0);
    var file = input.files && input.files[0];
    if (!maxSize || !file) {
      clearWarning(input);
      return true;
    }
    if (file.size > maxSize) {
      setWarning(
        input,
        "源码包压缩文件超过 " + formatMB(maxSize) +
          "MB 限制，当前 " + formatMB(file.size) + "MB。"
      );
      return false;
    }
    clearWarning(input);
    return true;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var inputs = document.querySelectorAll('input[type="file"][data-max-size]');
    Array.prototype.forEach.call(inputs, function (input) {
      input.addEventListener("change", function () {
        validate(input);
      });
      if (input.form) {
        input.form.addEventListener("submit", function (event) {
          if (!validate(input)) {
            event.preventDefault();
          }
        });
      }
    });
  });
})();
