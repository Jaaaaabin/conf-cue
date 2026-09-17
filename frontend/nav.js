const navToggle = document.getElementById("navToggle");
const navPanel = document.getElementById("navPanel");

function closeNav() {
  navPanel.classList.remove("is-open");
  navToggle.setAttribute("aria-expanded", "false");
}

navToggle.addEventListener("click", () => {
  const open = navPanel.classList.toggle("is-open");
  navToggle.setAttribute("aria-expanded", String(open));
});

document.addEventListener("click", (event) => {
  if (!navPanel.classList.contains("is-open")) return;
  if (navToggle.contains(event.target) || navPanel.contains(event.target)) return;
  closeNav();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && navPanel.classList.contains("is-open")) {
    closeNav();
    navToggle.focus();
  }
});
