(() => {
  const overlay = document.getElementById("networkRegister");
  const form = document.getElementById("nrForm");
  const message = document.getElementById("nrMessage");
  const submit = document.getElementById("nrSubmit");
  let currentPlayer = null;

  function showRegistration() {
    if (!overlay) return;
    overlay.hidden = false;
    document.getElementById("nrUsername").value = "";
    document.getElementById("nrPhone").value = "";
    document.getElementById("nrConsent").checked = false;
    message.textContent = "";
    submit.disabled = false;
    submit.textContent = "Entrar no jogo";
  }

  async function submitResult(result) {
    if (!currentPlayer) return;
    try {
      const response = await fetch("/api/finish", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(result), credentials: "same-origin"
      });
      const data = await response.json();
      const target = document.getElementById("endSummary");
      if (response.ok && target) {
        target.textContent += " • Resultado registrado no ranking oficial.";
      } else if (target) {
        target.textContent += " • Não foi possível sincronizar o resultado: " + (data.error || "erro de conexão") + ". Avise a organização.";
      }
    } catch (_) {
      const target = document.getElementById("endSummary");
      if (target) target.textContent += " • Falha de conexão com o servidor. Avise a organização antes de sair.";
    }
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.textContent = "";
    submit.disabled = true;
    submit.textContent = "Registrando...";
    const payload = {
      username: document.getElementById("nrUsername").value.trim(),
      phone: document.getElementById("nrPhone").value.trim(),
      consent: document.getElementById("nrConsent").checked
    };
    try {
      const response = await fetch("/api/register", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload), credentials: "same-origin"
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Não foi possível realizar o cadastro.");
      currentPlayer = data.username;
      overlay.hidden = true;
    } catch (error) {
      message.textContent = error.message;
      submit.disabled = false;
      submit.textContent = "Tentar novamente";
    }
  });

  window.NetworkGame = {showRegistration, submitResult};
  showRegistration();
})();
