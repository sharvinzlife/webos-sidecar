const util = require("node:util");
const utilTypes = require("node:util/types");

if (typeof util.isDate !== "function") {
  util.isDate = utilTypes.isDate;
}

