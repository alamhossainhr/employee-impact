'use strict';
(() => {
    const search = document.getElementById('employee-search');
    if (!search) return;
    const rows = Array.from(document.querySelectorAll('.employee-option'));
    const count = document.getElementById('employee-search-count');
    const empty = document.getElementById('employee-search-empty');
    const clear = document.getElementById('employee-search-clear');
    const normalize = value => value.normalize('NFKC').toLocaleLowerCase().trim();
    const indexed = rows.map(row => ({
        row, text: normalize(row.dataset.employeeSearch || ''),
        checkbox: row.querySelector('input[type="checkbox"]')
    }));
    function update() {
        const terms = normalize(search.value).split(/\s+/).filter(Boolean);
        let matches = 0, selected = 0;
        indexed.forEach(item => {
            const matched = terms.every(term => item.text.includes(term));
            item.row.hidden = !matched;
            if (matched) matches += 1;
            if (item.checkbox.checked) selected += 1;
        });
        count.textContent = `মিল পাওয়া গেছে: ${matches} / ${rows.length} · নির্বাচিত: ${selected}`;
        empty.hidden = matches > 0;
    }
    search.addEventListener('input', update);
    search.addEventListener('keydown', event => {
        if (event.key === 'Enter') event.preventDefault();
    });
    indexed.forEach(item => item.checkbox.addEventListener('change', update));
    clear.addEventListener('click', () => {
        search.value = '';
        update();
        search.focus();
    });
    update();
})();
