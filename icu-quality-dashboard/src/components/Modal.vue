<template>
  <div class="mask" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal-head">
        <span>{{ title }}</span>
        <span class="close" @click="$emit('close')">✕</span>
      </div>
      <div class="modal-body"><slot /></div>
    </div>
  </div>
</template>
<script setup>
defineProps({ title: String });
defineEmits(['close']);
</script>
<style scoped>
.mask { position:fixed; inset:0; background:rgba(0,0,0,0.4); display:flex;
  align-items:center; justify-content:center; z-index:100; }
.modal { background:#ffffff; border:1px solid rgba(0,0,0,0.08); border-radius:10px;
  width:min(760px,90vw); max-height:80vh; display:flex; flex-direction:column; box-shadow: 0 10px 25px rgba(0,0,0,0.1); }
.modal-head { display:flex; justify-content:space-between; padding:16px 20px;
  border-bottom:1px solid rgba(0,0,0,0.06); color:#1e293b; font-size:16px; font-weight:bold; }
.close { cursor:pointer; color:#64748b; }
.close:hover { color:#1e293b; }
.modal-body { padding:18px 20px; overflow-y:auto; }
</style>
