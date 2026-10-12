/* Drag and drop for instrument files on "Add measurement" (M2F-a).

   Progressive enhancement of the ordinary file fields: the form posts exactly
   what the fields hold, and the server checks every file as before.

   <div class="file-drop" data-drop-inputs="left_file right_file" data-drop-accept=".txt">
     A zone for several files at once. With two inputs (Mahr left/right), each file goes to the
     side named by the letter at the end of its name (…L.TXT → left, …R.TXT → right), as the
     Seal Face Flatness v5 tool places them; otherwise in the order given, into the empty fields first.
   Every file field of the form is a drop target for its own file as well.
*/
(function () {
  "use strict";

  function side(name) {
    var m = /([LR])\.[^.]*$/i.exec(name) || /([LR])$/i.exec(name);
    return m ? m[1].toUpperCase() : null;
  }

  function accepted(file, accept) {
    if (!accept) return true;
    var lower = file.name.toLowerCase();
    return accept.split(",").some(function (ext) { return lower.endsWith(ext.trim().toLowerCase()); });
  }

  function put(input, file) {
    var dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /* [{input, file}] for files dropped on the shared zone. */
  function assign(inputs, files) {
    if (inputs.length === 2 && files.length >= 2) {
      var left = files.find(function (f) { return side(f.name) === "L"; }) || files[0];
      var right = files.find(function (f) { return f !== left && side(f.name) === "R"; }) ||
                  files.find(function (f) { return f !== left; });
      return [{ input: inputs[0], file: left }, { input: inputs[1], file: right }];
    }
    var placed = [], free = inputs.filter(function (i) { return !i.files.length; });
    files.slice(0, inputs.length).forEach(function (file) {
      var guess = inputs.length === 2 ? side(file.name) : null;
      var input = guess === "L" ? inputs[0] : guess === "R" ? inputs[1] : (free.shift() || inputs[0]);
      free = free.filter(function (i) { return i !== input; });
      placed.push({ input: input, file: file });
    });
    return placed;
  }

  function dropTarget(el, onFiles) {
    el.addEventListener("dragover", function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, "Files") < 0) return;
      e.preventDefault();
      el.classList.add("drag-over");
    });
    el.addEventListener("dragleave", function (e) {
      if (!el.contains(e.relatedTarget)) el.classList.remove("drag-over");
    });
    el.addEventListener("drop", function (e) {
      e.preventDefault();
      el.classList.remove("drag-over");
      onFiles(Array.prototype.slice.call(e.dataTransfer.files));
    });
  }

  function enhance(zone) {
    var form = zone.closest("form");
    var accept = zone.dataset.dropAccept || "";
    var inputs = zone.dataset.dropInputs.split(/\s+/).map(function (name) {
      return form.querySelector('input[type="file"][name="' + name + '"]');
    });
    var status = zone.querySelector(".file-drop-status");
    var picker = zone.querySelector('input[type="file"].file-drop-picker');

    function report(text, isError) {
      status.textContent = text;
      status.classList.toggle("error", !!isError);
    }

    function take(files, onlyInput) {
      var wrong = files.filter(function (f) { return !accepted(f, accept); });
      if (wrong.length) {
        report(wrong.map(function (f) { return f.name; }).join(", ") + ": not a " + accept.toUpperCase() +
               " file. Nothing was placed.", true);
        return;
      }
      if (!files.length) return;
      if (files.length > inputs.length || (onlyInput && files.length > 1)) {
        report("Drop " + (onlyInput || inputs.length === 1 ? "one file" : "at most " + inputs.length + " files") +
               " here. Nothing was placed.", true);
        return;
      }
      var placed = onlyInput ? [{ input: onlyInput, file: files[0] }] : assign(inputs, files);
      placed.forEach(function (p) { put(p.input, p.file); });
      summary();
    }

    function summary() {
      var parts = inputs.map(function (input) {
        var label = form.querySelector('label[for="' + input.id + '"]');
        var name = input.files.length ? input.files[0].name : "—";
        return (label ? label.textContent.replace(/:\s*$/, "") : input.name) + ": " + name;
      });
      report(parts.join(" · "), false);
    }

    dropTarget(zone, function (files) { take(files, null); });
    inputs.forEach(function (input) {
      var field = input.closest(".field") || input.parentElement;
      field.classList.add("file-drop-field");
      dropTarget(field, function (files) { take(files, input); });
      input.addEventListener("change", summary);
    });
    if (picker) {
      zone.querySelector(".file-drop-choose").addEventListener("click", function () { picker.click(); });
      zone.addEventListener("keydown", function (e) {
        if ((e.key === "Enter" || e.key === " ") && e.target === zone) { e.preventDefault(); picker.click(); }
      });
      picker.addEventListener("change", function () {
        take(Array.prototype.slice.call(picker.files), null);
        picker.value = "";
      });
    }
    zone.hidden = false;
  }

  document.querySelectorAll(".file-drop").forEach(enhance);
})();
