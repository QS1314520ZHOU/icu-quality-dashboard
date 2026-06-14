<template>
  <div ref="el" style="width:100%;height:320px;"></div>
</template>
<script setup>
import { ref, onMounted } from 'vue';
import * as echarts from 'echarts';
const props = defineProps({ data: Object });
const el = ref(null);
onMounted(() => {
  echarts.init(el.value).setOption({
    tooltip: { trigger:'axis' },
    grid: { left:45, right:25, top:30, bottom:30 },
    xAxis: { type:'category', data:props.data.months,
      axisLine:{lineStyle:{color:'rgba(0,0,0,0.12)'}}, axisLabel:{color:'#64748b'} },
    yAxis: { type:'value', splitLine:{lineStyle:{color:'rgba(0,0,0,0.05)'}},
      axisLabel:{color:'#64748b'} },
    series: [{ type:'line', data:props.data.values, smooth:true, connectNulls:false,
      lineStyle:{color:'#0052d9',width:2}, itemStyle:{color:'#10b981'},
      areaStyle:{color:'rgba(0,82,217,0.05)'} }],
  });
});
</script>
