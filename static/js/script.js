
const $ = (id) => document.getElementById(id);

const money = (value) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2
  }).format(value || 0);

const today = new Date();
$("monthFilter").value =
  `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
$("txDate").value =
  `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

let chart = null;
let incomeExpenseChart = null;
let budgetComparisonChart = null;
let monthlyTrendsChart = null;
let currentTransactions = [];

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers
    }
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }

  return data;
}

function showMessage(message, isError = false) {
  $("message").textContent = message;
  $("message").style.color = isError ? "#b91c1c" : "#15803d";
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);
}

function selectedMonth() {
  return $("monthFilter").value;
}
function updateExportLinks() {
  const month = encodeURIComponent(selectedMonth());
  $("exportCsv").href = `/api/export/csv?month=${month}`;
  $("exportPdf").href = `/api/export/pdf?month=${month}`;
}
async function loadSummary() {
  const data = await api(`/api/summary?month=${encodeURIComponent(selectedMonth())}`);
  renderFinancialInsights(data);
  renderMonthComparison(data);
    $("incomeExpenseEmpty").hidden =
    Number(data.income) > 0 || Number(data.expenses) > 0;

  if (incomeExpenseChart) {
    incomeExpenseChart.destroy();
    incomeExpenseChart = null;
  }

  if (Number(data.income) > 0 || Number(data.expenses) > 0) {
    incomeExpenseChart = new Chart($("incomeExpenseChart"), {
      type: "bar",
      data: {
        labels: ["Income", "Expenses"],
        datasets: [{
          label: "Amount (₹)",
          data: [data.income, data.expenses],
          backgroundColor: ["#16a34a", "#dc2626"],
          borderRadius: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (context) => money(context.raw)
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: (value) => money(value)
            }
          }
        }
      }
    });
  }
  $("balance").textContent = money(data.balance);
  $("income").textContent = money(data.income);
  $("expenses").textContent = money(data.expenses);
  $("savingsRate").textContent = `${data.savings_rate}%`;

  const labels = data.categories.map((item) => item.category);
  const values = data.categories.map((item) => item.total);

  $("chartEmpty").hidden = values.length > 0;

  if (chart) chart.destroy();

  if (values.length) {
    chart = new Chart($("expenseChart"), {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data: values }]
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom" } }
      }
    });
  }
}


function renderFinancialInsights(data) {
  const income = Number(data.income || 0);
  const expenses = Number(data.expenses || 0);
  const balance = Number(data.balance ?? income - expenses);
  const savingsRate = Number(data.savings_rate || 0);
  const categories = Array.isArray(data.categories) ? data.categories : [];

  $("insightIncome").textContent = money(income);
  $("insightExpenses").textContent = money(expenses);
  $("insightBalance").textContent = money(balance);
  $("insightSavingsRate").textContent = `${savingsRate.toFixed(2)}%`;

  const message = $("financialInsightMessage");

  if (income === 0 && expenses === 0) {
    message.textContent =
      "Is month abhi koi financial activity record nahi hui hai.";
  } else if (income === 0 && expenses > 0) {
    message.textContent =
      `Aapne ${money(expenses)} spend kiye hain, lekin income record nahi hui. Apni income entries add karein aur expenses review karein.`;
  } else if (balance < 0) {
    message.textContent =
      `Overspending alert: expenses income se ${money(Math.abs(balance))} zyada hain. Non-essential spending review karein.`;
  } else if (balance === 0) {
    message.textContent =
      "Income aur expenses equal hain. Savings badhane ke liye kuch expenses reduce karein.";
  } else {
    message.textContent =
      `Achha! Is month ${money(balance)} bache hain. Savings habit continue rakhein.`;
  }

  // Highest spending category
  const highestCategory = categories.reduce((highest, item) => {
    return Number(item.total) > Number(highest?.total || 0)
      ? item
      : highest;
  }, null);

  let categoryInsight = $("highestSpendingInsight");

  if (!categoryInsight) {
    categoryInsight = document.createElement("p");
    categoryInsight.id = "highestSpendingInsight";
    message.insertAdjacentElement("afterend", categoryInsight);
  }

  categoryInsight.textContent = highestCategory
    ? `Highest spending: ${highestCategory.category} (${money(highestCategory.total)}). Is category ke expenses review karein.`
    : "Highest spending category dikhane ke liye expense entries add karein.";

  // Expense-to-income ratio
  let ratioInsight = $("expenseRatioInsight");

  if (!ratioInsight) {
    ratioInsight = document.createElement("p");
    ratioInsight.id = "expenseRatioInsight";
    categoryInsight.insertAdjacentElement("afterend", ratioInsight);
  }

  ratioInsight.textContent = income > 0
    ? `Income ka ${((expenses / income) * 100).toFixed(2)}% expenses mein ja raha hai.`
    : "Expense-to-income ratio calculate karne ke liye income record karein.";

  // Savings recommendation
  let recommendation = $("savingsRecommendation");

  if (!recommendation) {
    recommendation = document.createElement("p");
    recommendation.id = "savingsRecommendation";
    ratioInsight.insertAdjacentElement("afterend", recommendation);
  }

  if (income <= 0) {
    recommendation.textContent =
      "Suggestion: Apni income aur expenses ko regularly record karein.";
  } else if (balance < 0) {
    recommendation.textContent =
      `Suggestion: Pehle deficit cover karne par focus karein. Expenses ko kam se kam ${money(Math.abs(balance))} reduce karna hoga taaki is month balance zero ho.`;
  } else {
    const targetSavings = income * 0.20;
    const gap = Math.max(0, targetSavings - balance);

    recommendation.textContent = gap > 0
      ? `Suggestion: 20% savings target ke liye is month aur ${money(gap)} save karne ka goal rakhein.`
      : "Great! Aap is month income ka 20% ya usse zyada save kar rahe hain.";
  }
}


function renderMonthComparison(data) {
  $("comparisonMonth").textContent = data.month || "—";
  $("previousMonth").textContent = data.previous_month || "—";

  $("previousIncome").textContent = money(data.previous_income);
  $("previousExpenses").textContent = money(data.previous_expenses);
  $("previousBalance").textContent = money(data.previous_balance);
  $("comparisonBalance").textContent = money(data.balance);

  function formatChange(value, kind) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return "N/A";
    }

    const percent = Number(value);
    const prefix = percent > 0 ? "+" : "";
    const suffix = "%";

    if (kind === "expense") {
      if (percent > 0) return `↑ ${prefix}${percent.toFixed(2)}%`;
      if (percent < 0) return `↓ ${percent.toFixed(2)}%`;
      return "0.00%";
    }

    if (percent > 0) return `↑ ${prefix}${percent.toFixed(2)}%`;
    if (percent < 0) return `↓ ${percent.toFixed(2)}%`;
    return `0.00${suffix}`;
  }

  const incomeChange = $("incomeChange");
  const expenseChange = $("expenseChange");

  incomeChange.textContent = formatChange(
    data.income_change_percent,
    "income"
  );

  expenseChange.textContent = formatChange(
    data.expense_change_percent,
    "expense"
  );

  incomeChange.style.color =
    Number(data.income_change_percent) > 0 ? "#15803d" :
    Number(data.income_change_percent) < 0 ? "#b91c1c" : "";

  expenseChange.style.color =
    Number(data.expense_change_percent) > 0 ? "#b91c1c" :
    Number(data.expense_change_percent) < 0 ? "#15803d" : "";
}

async function loadTransactions() {
  const params = new URLSearchParams({
    month: selectedMonth(),
    search: $("search").value,
    kind: $("typeFilter").value,
    category: $("categoryFilter").value
  });

  currentTransactions = await api(`/api/transactions?${params}`);

  
  const sortMode = $("sortTransactions").value;

  currentTransactions.sort((a, b) => {
    const dateA = String(a.tx_date ?? a.txn_date ?? "");
    const dateB = String(b.tx_date ?? b.txn_date ?? "");

    if (sortMode === "newest") {
      return dateB.localeCompare(dateA) || Number(b.id) - Number(a.id);
    }

    if (sortMode === "oldest") {
      return dateA.localeCompare(dateB) || Number(a.id) - Number(b.id);
    }

    if (sortMode === "amount-high") {
      return Number(b.amount || 0) - Number(a.amount || 0);
    }

    if (sortMode === "amount-low") {
      return Number(a.amount || 0) - Number(b.amount || 0);
    }

    if (sortMode === "title") {
      return String(a.title ?? "").localeCompare(String(b.title ?? ""));
    }

    return 0;
  });

  $("transactionCount").textContent =
    `${currentTransactions.length} transaction(s) found`;


  $("transactionCount").textContent =
    `${currentTransactions.length} transaction(s) found`;

  const tbody = $("transactionList");

  tbody.innerHTML = currentTransactions.map((tx) => `
    <tr>
      <td>${escapeHTML(tx.txn_date ?? tx.tx_date ?? "")}</td>
      <td>${escapeHTML(tx.title)}</td>
      <td>${escapeHTML(tx.category)}</td>
      <td class="${tx.kind === "income" ? "income-text" : "expense-text"}">
        ${tx.kind === "income" ? "Income" : "Expense"}
      </td>
      <td>${money(tx.amount)}</td>
      <td>
        <div class="actions">
          <button type="button" data-edit="${tx.id}">Edit</button>
          <button type="button" class="delete" data-delete="${tx.id}">Delete</button>
        </div>
      </td>
    </tr>
  `).join("");

  $("emptyState").hidden = currentTransactions.length > 0;
}


async function loadBudgets() {
  const budgets = await api(
    `/api/budgets?month=${encodeURIComponent(selectedMonth())}`
  );

  $("budgetList").innerHTML = budgets.map((budget) => {
    const amount = Number(budget.amount || 0);
    const spent = Number(budget.spent || 0);
    const actualPercent = amount > 0 ? (spent / amount) * 100 : 0;
    const barWidth = Math.min(actualPercent, 100);

    let status = `${money(budget.remaining)} remaining`;
    let level = "safe";

    if (actualPercent >= 100) {
      level = "over";
      status = spent > amount
        ? `Over budget by ${money(spent - amount)} (${actualPercent.toFixed(1)}% used)`
        : `Budget fully used (100%)`;
    } else if (actualPercent >= 75) {
      level = "warning";
    }

    return `
      <div class="budget-item">
        <div class="budget-heading">
          <strong>${escapeHTML(budget.category)}</strong>
          <span>${money(spent)} / ${money(amount)}</span>
        </div>
        <div
          class="progress"
          role="progressbar"
          aria-label="${escapeHTML(budget.category)} budget usage"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow="${Math.min(actualPercent, 100)}"
        >
          <div class="${level}" style="width:${barWidth}%"></div>
        </div>
        <small>${status}</small>
      </div>
    `;
  }).join("");

  budgets
    .filter((budget) => Number(budget.spent) > Number(budget.amount))
    .forEach((budget) => {
      console.warn(`Budget exceeded: ${budget.category}`);
    });
}


async function loadBudgetComparison() {
  const canvas = $("budgetComparisonChart");
  const empty = $("budgetComparisonEmpty");

  const budgets = await api(
    `/api/budgets?month=${encodeURIComponent(selectedMonth())}`
  );

  if (budgetComparisonChart) {
    budgetComparisonChart.destroy();
    budgetComparisonChart = null;
  }

  if (!budgets.length) {
    empty.hidden = false;
    canvas.hidden = true;
    return;
  }

  empty.hidden = true;
  canvas.hidden = false;

  const labels = budgets.map((item) => item.category);
  const budgetAmounts = budgets.map((item) => Number(item.amount || 0));
  const actualAmounts = budgets.map((item) => Number(item.spent || 0));

  budgetComparisonChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Budget",
          data: budgetAmounts,
          backgroundColor: "#2563eb",
          borderRadius: 5
        },
        {
          label: "Actual Spending",
          data: actualAmounts,
          backgroundColor: actualAmounts.map((spent, index) =>
            spent > budgetAmounts[index] ? "#dc2626" : "#16a34a"
          ),
          borderRadius: 5
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            callback: (value) => money(value)
          }
        }
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (context) =>
              `${context.dataset.label}: ${money(context.raw)}`
          }
        }
      }
    }
  });
}

async function loadBudgetAlerts() {
  const data = await api(
    `/api/budget-alerts?month=${encodeURIComponent(selectedMonth())}`
  );

  const container = $("budget-alerts-list");

  if (!data.alerts || data.alerts.length === 0) {
    container.innerHTML = `
      <p class="alert-normal">
        Is month ke liye koi budget set nahi hai.
      </p>
    `;
    return;
  }

  container.innerHTML = data.alerts.map((alert) => {
    let cssClass = "alert-normal";
    let icon = "✓";

    if (alert.status === "exceeded") {
      cssClass = "alert-exceeded";
      icon = "⚠️";
    } else if (alert.status === "warning") {
      cssClass = "alert-warning";
      icon = "⚠️";
    }

    return `
      <div class="budget-alert ${cssClass}">
        <div>
          <strong>${icon} ${escapeHTML(alert.category)}</strong>
          <p>${escapeHTML(alert.message)}</p>
        </div>

        <div class="budget-alert-details">
          <span>Spent: ${money(alert.spent)}</span>
          <span>Budget: ${money(alert.budget)}</span>
          <span>Used: ${alert.percent_used}%</span>
        </div>
      </div>
    `;
  }).join("");
}

async function loadMonthlyTrends() {
  const canvas = $("monthlyTrendsChart");
  const message = $("monthlyTrendsMessage");

  const trends = await api("/api/monthly-trends");

  if (monthlyTrendsChart) {
    monthlyTrendsChart.destroy();
    monthlyTrendsChart = null;
  }

  if (!trends.length) {
    canvas.hidden = true;
    message.hidden = false;
    message.textContent = "No monthly transaction data available.";
    return;
  }

  canvas.hidden = false;
  message.hidden = true;

  monthlyTrendsChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: trends.map((item) => item.month),
      datasets: [
        {
          label: "Income",
          data: trends.map((item) => Number(item.income)),
          borderColor: "#16a34a",
          backgroundColor: "#16a34a",
          tension: 0.3
        },
        {
          label: "Expenses",
          data: trends.map((item) => Number(item.expenses)),
          borderColor: "#dc2626",
          backgroundColor: "#dc2626",
          tension: 0.3
        },
        {
          label: "Savings",
          data: trends.map((item) => Number(item.savings)),
          borderColor: "#2563eb",
          backgroundColor: "#2563eb",
          tension: 0.3
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: {
        mode: "index",
        intersect: false
      },
      scales: {
        y: {
          ticks: {
            callback: (value) => money(value)
          }
        }
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: (context) =>
              `${context.dataset.label}: ${money(context.raw)}`
          }
        }
      }
    }
  });
}


async function refreshDashboard() {
  try {
    await Promise.all([
      loadSummary(),
      loadTransactions(),
      loadBudgets(),
      loadBudgetAlerts(),
      loadBudgetComparison(),
      loadMonthlyTrends()
    ]);
  } catch (error) {
    showMessage(error.message, true);
  }
}


$("transactionForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const id = $("transactionId").value;
  const payload = {
    title: $("title").value.trim(),
    amount: Number($("amount").value),
    kind: $("kind").value,
    category: $("category").value,
    tx_date: $("txDate").value
  };

  try {
    await api(
      id ? `/api/transactions/${id}` : "/api/transactions",
      {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(payload)
      }
    );

    $("transactionForm").reset();
    $("transactionId").value = "";
    $("txDate").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    $("saveButton").textContent = "Add transaction";
    $("cancelEdit").hidden = true;

    showMessage(id ? "Transaction updated." : "Transaction added.");
    await refreshDashboard();
  } catch (error) {
    showMessage(error.message, true);
  }
});

$("transactionList").addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit]");
  const deleteButton = event.target.closest("[data-delete]");

  if (editButton) {
    const tx = currentTransactions.find(
      (item) => item.id === Number(editButton.dataset.edit)
    );
    if (!tx) return;

    $("transactionId").value = tx.id;
    $("title").value = tx.title;
    $("amount").value = tx.amount;
    $("kind").value = tx.kind;
    $("category").value = tx.category;
    $("txDate").value = tx.txn_date ?? tx.tx_date ?? "";
    $("saveButton").textContent = "Update transaction";
    $("cancelEdit").hidden = false;
    $("transactionForm").scrollIntoView({ behavior: "smooth" });
  }

  if (deleteButton) {
    const id = Number(deleteButton.dataset.delete);
    if (!confirm("Delete this transaction?")) return;

    try {
      await api(`/api/transactions/${id}`, { method: "DELETE" });
      showMessage("Transaction deleted.");
      await refreshDashboard();
    } catch (error) {
      showMessage(error.message, true);
    }
  }
});

$("cancelEdit").addEventListener("click", () => {
  $("transactionForm").reset();
  $("transactionId").value = "";
  $("txDate").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  $("saveButton").textContent = "Add transaction";
  $("cancelEdit").hidden = true;
});

$("budgetForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  try {
    await api("/api/budgets", {
      method: "POST",
      body: JSON.stringify({
        category: $("budgetCategory").value,
        amount: Number($("budgetAmount").value)
      })
    });

    $("budgetForm").reset();
    
showMessage("Budget saved.");

await Promise.all([
  loadBudgets(),
  loadBudgetComparison(),
  loadBudgetAlerts()
]);

  } catch (error) {
    showMessage(error.message, true);
  }
});

$("monthFilter").addEventListener("change", () => {
  updateExportLinks();
  refreshDashboard();
});

let searchTimer;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadTransactions().catch(
    (error) => showMessage(error.message, true)
  ), 250);
});

$("typeFilter").addEventListener("change", () => {
  loadTransactions().catch((error) => showMessage(error.message, true));
});

$("categoryFilter").addEventListener("change", () => {
  loadTransactions().catch((error) => showMessage(error.message, true));
});
$("sortTransactions").addEventListener("change", () => {
  loadTransactions().catch((error) => showMessage(error.message, true));
});

refreshDashboard();
updateExportLinks();
