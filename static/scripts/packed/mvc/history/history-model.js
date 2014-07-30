define(["mvc/history/history-contents","mvc/base-mvc","utils/localization"],function(e,a,b){var d=Backbone.Model.extend(a.LoggableMixin).extend({defaults:{model_class:"History",id:null,name:"Unnamed History",state:"new",diskSize:0,deleted:false},urlRoot:galaxy_config.root+"api/histories",initialize:function(h,i,g){g=g||{};this.logger=g.logger||null;this.log(this+".initialize:",h,i,g);this.log("creating history contents:",i);this.hdas=new e.HistoryContents(i||[],{historyId:this.get("id")});this._setUpListeners();this.updateTimeoutId=null},_setUpListeners:function(){this.on("error",function(h,k,g,j,i){this.errorHandler(h,k,g,j,i)});if(this.hdas){this.listenTo(this.hdas,"error",function(){this.trigger.apply(this,["error:hdas"].concat(jQuery.makeArray(arguments)))})}this.on("change:id",function(h,g){if(this.hdas){this.hdas.historyId=g}},this)},errorHandler:function(h,k,g,j,i){this.clearUpdateTimeout()},ownedByCurrUser:function(){if(!Galaxy||!Galaxy.currUser){return false}if(Galaxy.currUser.isAnonymous()||Galaxy.currUser.id!==this.get("user_id")){return false}return true},hdaCount:function(){return _.reduce(_.values(this.get("state_details")),function(g,h){return g+h},0)},checkForUpdates:function(g){if(this.hdas.running().length){this.setUpdateTimeout()}else{this.trigger("ready");if(_.isFunction(g)){g.call(this)}}return this},setUpdateTimeout:function(g){g=g||d.UPDATE_DELAY;var h=this;this.clearUpdateTimeout();this.updateTimeoutId=setTimeout(function(){h.refresh()},g);return this.updateTimeoutId},clearUpdateTimeout:function(){if(this.updateTimeoutId){clearTimeout(this.updateTimeoutId);this.updateTimeoutId=null}},refresh:function(h,g){h=h||[];g=g||{};var i=this;g.data=g.data||{};if(h.length){g.data.details=h.join(",")}var j=this.hdas.fetch(g);j.done(function(k){i.checkForUpdates(function(){this.fetch()})});return j},toString:function(){return"History("+this.get("id")+","+this.get("name")+")"}});d.UPDATE_DELAY=4000;d.getHistoryData=function f(g,s){s=s||{};var m=s.hdaDetailIds||[];var i=s.hdcaDetailIds||[];var o=jQuery.Deferred(),n=null;function h(t){return jQuery.ajax(galaxy_config.root+"api/histories/"+g)}function l(t){return t&&t.empty}function r(u){if(l(u)){return[]}if(_.isFunction(m)){m=m(u)}if(_.isFunction(i)){i=i(u)}var t={};if(m.length){t.dataset_details=m.join(",")}if(i.length){t.dataset_collection_details=i.join(",")}return jQuery.ajax(galaxy_config.root+"api/histories/"+u.id+"/contents",{data:t})}var q=s.historyFn||h,p=s.hdaFn||r;var k=q(g);k.done(function(t){n=t;o.notify({status:"history data retrieved",historyJSON:n})});k.fail(function(v,t,u){o.reject(v,"loading the history")});var j=k.then(p);j.then(function(t){o.notify({status:"dataset data retrieved",historyJSON:n,hdaJSON:t});o.resolve(n,t)});j.fail(function(v,t,u){o.reject(v,"loading the datasets",{history:n})});return o};var c=Backbone.Collection.extend(a.LoggableMixin).extend({model:d,urlRoot:galaxy_config.root+"api/histories"});return{History:d,HistoryCollection:c}});