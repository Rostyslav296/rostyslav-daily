// Rostyslav Daily: the little the pages need. Nothing here is required to read a story.
(function () {
    // The masthead's date is written when the site is built; show the reader's own today.
    var line = document.querySelector("[data-dateline]");
    if (line) {
        try {
            line.textContent = new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
        } catch (e) {}
    }
    // "3 hours ago" beside recent stories; the full date stays in the tooltip.
    var now = Date.now();
    document.querySelectorAll("time[datetime]").forEach(function (t) {
        var then = Date.parse(t.getAttribute("datetime"));
        if (isNaN(then)) return;
        var minutes = Math.round((now - then) / 60000);
        if (minutes < 0 || minutes > 60 * 20) return;
        t.title = t.textContent;
        t.textContent = minutes < 2 ? "just now" : minutes < 60 ? minutes + " minutes ago"
            : Math.round(minutes / 60) === 1 ? "1 hour ago" : Math.round(minutes / 60) + " hours ago";
    });
    // Keep the current section's tab in view on a narrow screen.
    var current = document.querySelector('.nav a[aria-current="page"]');
    if (current && current.scrollIntoView) current.scrollIntoView({ inline: "center", block: "nearest" });
})();
