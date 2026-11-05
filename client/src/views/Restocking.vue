<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <!-- Budget control stays mounted while recommendations reload so dragging is never interrupted -->
    <div class="card budget-card">
      <div class="budget-row">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budgetControl') }}</label>
        <div class="budget-value">{{ formatMoney(budget) }}</div>
      </div>
      <input
        id="budget-slider"
        v-model.number="budget"
        class="budget-slider"
        type="range"
        :min="BUDGET_MIN"
        :max="BUDGET_MAX"
        :step="BUDGET_STEP"
      />
      <div class="budget-scale">
        <span>{{ formatMoney(BUDGET_MIN) }}</span>
        <span>{{ formatMoney(BUDGET_MAX) }}</span>
      </div>
    </div>

    <div v-if="initialLoading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else :class="{ refreshing: refreshing }">
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(budget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.selectedTotal') }}</div>
          <div class="stat-value">{{ formatMoney(selectedTotal, 2) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatMoney(remaining, 2) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.fullShortfallCost') }}</div>
          <div class="stat-value">{{ formatMoney(fullShortfallCost) }}</div>
        </div>
      </div>

      <!-- Confirmation panel after a successful order -->
      <div v-if="lastOrder" class="order-confirmation" role="status">
        <div class="confirmation-title">{{ t('restocking.orderPlaced') }}</div>
        <dl class="confirmation-details">
          <div>
            <dt>{{ t('restocking.orderId') }}</dt>
            <dd>{{ lastOrder.id }}</dd>
          </div>
          <div>
            <dt>{{ t('restocking.orderTotal') }}</dt>
            <dd>{{ formatMoney(lastOrder.total_cost, 2) }}</dd>
          </div>
          <div>
            <dt>{{ t('restocking.leadTime') }}</dt>
            <dd>{{ t('restocking.days', { count: lastOrder.lead_time_days }) }}</dd>
          </div>
          <div>
            <dt>{{ t('restocking.expectedDelivery') }}</dt>
            <dd>{{ formatDateOnly(lastOrder.expected_delivery, currentLocale) }}</dd>
          </div>
        </dl>
        <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>

      <div v-if="submitError" class="error" role="alert">
        {{ t('restocking.orderFailed') }}: {{ submitError }}
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            {{ t('restocking.recommendedItems') }}
            <span v-if="items.length" class="selected-count">
              {{ t('restocking.selectedCount', { selected: selectedItems.length, total: items.length }) }}
            </span>
          </h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="!canSubmit"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="items.length === 0" class="empty-state">
          <!-- Distinguish "budget too small" from "nothing is short" via the full shortfall cost -->
          {{ fullShortfallCost > 0 ? t('restocking.emptyBudget') : t('restocking.emptyNothingNeeded') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th class="col-check">{{ t('restocking.table.select') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.stock') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.sku" :class="{ unchecked: !checked[item.sku] }">
                <td class="col-check">
                  <input
                    v-model="checked[item.sku]"
                    type="checkbox"
                    :aria-label="`${t('restocking.table.select')} ${item.sku}`"
                  />
                </td>
                <td>
                  <strong>{{ item.sku }}</strong>
                  <div class="item-name">{{ translateProductName(item.name) }}</div>
                </td>
                <td>{{ translateCategory(item.category) }}</td>
                <td>{{ item.current_stock }} / {{ item.forecasted_demand }}</td>
                <td>{{ item.shortfall }}</td>
                <td>
                  <strong>{{ item.recommended_qty }}</strong>
                  <span
                    v-if="item.recommended_qty < item.shortfall"
                    class="badge warning partial-badge"
                    :title="t('restocking.partialTitle')"
                  >{{ t('restocking.partial') }}</span>
                </td>
                <td>{{ formatMoney(item.unit_cost, 2) }}</td>
                <td><strong>{{ formatMoney(item.line_cost, 2) }}</strong></td>
                <td>{{ t('restocking.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'
import { formatDateOnly } from '../utils/dateFormat'

const BUDGET_MIN = 0
const BUDGET_MAX = 50000
const BUDGET_STEP = 500
const DEFAULT_BUDGET = 15000
const DEBOUNCE_MS = 250

export default {
  name: 'Restocking',
  setup() {
    const { t, currentLocale, currentCurrency, translateProductName } = useI18n()

    // NOTE: The global FilterBar (period / warehouse / category / status) intentionally does
    // not apply here: restocking works off the whole demand forecast, so useFilters is not used.

    const budget = ref(DEFAULT_BUDGET)
    const items = ref([])
    const fullShortfallCost = ref(0)
    // sku -> checked state; rebuilt (all true) every time recommendations reload
    const checked = ref({})

    const initialLoading = ref(true)
    const refreshing = ref(false)
    const error = ref(null)
    const submitting = ref(false)
    const submitError = ref(null)
    const lastOrder = ref(null)

    // True between a slider change and the debounced fetch finishing; the displayed
    // items are stale for the current slider value during that window.
    const pendingFetch = ref(false)

    let debounceTimer = null
    // Monotonic request counter: a response is applied only if no newer request was issued
    let requestSeq = 0

    const formatMoney = (amount, decimals = 0) => {
      return decimals > 0
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    const translateCategory = (category) => {
      const map = {
        'Circuit Boards': 'categories.circuitBoards',
        'Sensors': 'categories.sensors',
        'Actuators': 'categories.actuators',
        'Controllers': 'categories.controllers',
        'Power Supplies': 'categories.powerSupplies'
      }
      return map[category] ? t(map[category]) : category
    }

    const loadRecommendations = async () => {
      const seq = ++requestSeq
      pendingFetch.value = false
      refreshing.value = true
      try {
        const data = await api.getRestockRecommendations(budget.value)
        if (seq !== requestSeq) return // a newer request superseded this one
        items.value = data.items
        fullShortfallCost.value = data.full_shortfall_cost
        // Reset every row to checked whenever recommendations reload
        const next = {}
        data.items.forEach(item => { next[item.sku] = true })
        checked.value = next
        error.value = null
      } catch (err) {
        if (seq !== requestSeq) return
        error.value = t('restocking.loadFailed') + ': ' + (err.response?.data?.detail || err.message)
      } finally {
        if (seq === requestSeq) {
          refreshing.value = false
          initialLoading.value = false
        }
      }
    }

    // Debounce fetches while the slider is being dragged
    watch(budget, () => {
      pendingFetch.value = true
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendations, DEBOUNCE_MS)
    })

    const selectedItems = computed(() => items.value.filter(item => checked.value[item.sku]))

    // Sum in cents to avoid floating point drift when toggling many rows
    const selectedTotal = computed(() => {
      const cents = selectedItems.value.reduce((sum, item) => sum + Math.round(item.line_cost * 100), 0)
      return cents / 100
    })

    const remaining = computed(() => Math.round((budget.value - selectedTotal.value) * 100) / 100)

    // Block submission while items are stale relative to the slider (pending/in-flight fetch)
    const canSubmit = computed(() =>
      selectedItems.value.length > 0 &&
      !submitting.value &&
      !refreshing.value &&
      !pendingFetch.value
    )

    const placeOrder = async () => {
      // Guard against double-submit even if the disabled state hasn't rendered yet
      if (!canSubmit.value) return
      submitting.value = true
      submitError.value = null
      lastOrder.value = null
      try {
        // Only checked rows are sent, each with its own recommended_qty
        const payload = {
          budget: budget.value,
          items: selectedItems.value.map(item => ({ sku: item.sku, quantity: item.recommended_qty }))
        }
        lastOrder.value = await api.placeRestockOrder(payload)
        // Stock/shortfalls changed server-side; reload (also resets checkboxes)
        await loadRecommendations()
      } catch (err) {
        submitError.value = err.response?.data?.detail || err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    onBeforeUnmount(() => {
      clearTimeout(debounceTimer)
      requestSeq++ // invalidate any in-flight response
    })

    return {
      t,
      currentLocale,
      translateProductName,
      translateCategory,
      formatMoney,
      formatDateOnly,
      BUDGET_MIN,
      BUDGET_MAX,
      BUDGET_STEP,
      budget,
      items,
      fullShortfallCost,
      checked,
      initialLoading,
      refreshing,
      error,
      submitting,
      submitError,
      lastOrder,
      selectedItems,
      selectedTotal,
      remaining,
      canSubmit,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.budget-label {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.budget-value {
  font-size: 2.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

/* Range slider: slate track, blue thumb (vendor-prefixed rules cannot be combined) */
.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  background: #2563eb;
  border: 3px solid white;
  border-radius: 50%;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
  transition: transform 0.15s ease;
}

.budget-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: #2563eb;
  border: 3px solid white;
  border-radius: 50%;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
}

.budget-slider::-moz-range-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
}

.budget-slider:hover::-webkit-slider-thumb {
  transform: scale(1.1);
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

.budget-slider:focus-visible::-moz-range-thumb {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}

/* Dim content while a refetch is in flight without unmounting it */
.refreshing {
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.selected-count {
  margin-left: 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #64748b;
}

.place-order-btn {
  padding: 0.75rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, opacity 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.col-check {
  width: 64px;
  text-align: center;
}

.col-check input {
  width: 16px;
  height: 16px;
  accent-color: #2563eb;
  cursor: pointer;
}

.item-name {
  font-size: 0.813rem;
  color: #64748b;
}

tr.unchecked td {
  color: #94a3b8;
}

.partial-badge {
  margin-left: 0.5rem;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
}

.order-confirmation {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 10px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}

.confirmation-title {
  font-weight: 700;
  color: #166534;
  margin-bottom: 0.75rem;
}

.confirmation-details {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1rem;
  margin: 0 0 0.75rem;
}

.confirmation-details dt {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
}

.confirmation-details dd {
  margin: 0.25rem 0 0;
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
}

.confirmation-link {
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.confirmation-link:hover {
  text-decoration: underline;
}
</style>
