/**
 * This component deals with item selection inside a history.
 * It allows to select individual items or perform a query selection.
 */

import { getFilters, testFilters } from "store/historyStore/model/filtering";

export default {
    props: {
        scopeKey: { type: String, required: true },
        getItemKey: { type: Function, required: true },
        filterText: { type: String, required: true },
        totalItemsInQuery: { type: Number, required: false },
    },
    data() {
        return {
            items: new Map(),
            showSelection: false,
            allSelected: false,
        };
    },
    computed: {
        selectionSize() {
            return this.isQuerySelection ? this.totalItemsInQuery : this.items.size;
        },
        isQuerySelection() {
            return this.allSelected && this.totalItemsInQuery !== this.items.size;
        },
        currentFilters() {
            return getFilters(this.filterText);
        },
    },
    methods: {
        setShowSelection(val) {
            this.showSelection = val;
        },
        selectAllInCurrentQuery(loadedItems = []) {
            this.selectItems(loadedItems);
            this.allSelected = true;
        },
        isSelected(item) {
            if (this.isQuerySelection) {
                return testFilters(this.currentFilters, item);
            }
            const key = this.getItemKey(item);
            return this.items.has(key);
        },
        setSelected(item, selected) {
            const key = this.getItemKey(item);
            const newSelected = new Map(this.items);
            selected ? newSelected.set(key, item) : newSelected.delete(key);
            this.items = newSelected;
            this.resetQuerySelection();
        },
        selectItems(items = []) {
            const newItems = [...this.items.values(), ...items];
            const newEntries = newItems.map((item) => {
                const key = this.getItemKey(item);
                return [key, item];
            });
            this.items = new Map(newEntries);
            this.resetQuerySelection();
        },
        resetQuerySelection() {
            this.allSelected = false;
        },
        reset() {
            this.items = new Map();
            this.resetQuerySelection();
        },
        cancelSelection() {
            this.showSelection = false;
        },
    },
    watch: {
        scopeKey(newKey, oldKey) {
            if (newKey !== oldKey) {
                this.reset();
                this.cancelSelection();
            }
        },
        selectionSize(newSize) {
            if (newSize > 0) {
                this.showSelection = true;
            }
        },
        showSelection(newVal) {
            if (!newVal) {
                this.reset();
            }
        },
        totalItemsInQuery(newVal, oldVal) {
            if (this.allSelected && newVal !== oldVal) {
                this.resetQuerySelection();
            }
        },
    },
    render() {
        return this.$scopedSlots.default({
            selectedItems: this.items,
            showSelection: this.showSelection,
            isQuerySelection: this.isQuerySelection,
            selectionSize: this.selectionSize,
            setShowSelection: this.setShowSelection,
            selectAllInCurrentQuery: this.selectAllInCurrentQuery,
            selectItems: this.selectItems,
            isSelected: this.isSelected,
            setSelected: this.setSelected,
            resetSelection: this.reset,
        });
    },
};
