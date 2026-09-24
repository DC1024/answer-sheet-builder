// 题型注册表：聚合所有模块，便于扩展（新增题型只需 import 并加入列表）
import info from '../blocks/info.js';
import singleChoice from '../blocks/singleChoice.js';
import fillBlank from '../blocks/fillBlank.js';
import answer from '../blocks/answer.js';
import image from '../blocks/image.js';
import custom from '../blocks/custom.js';

const modules = [info, singleChoice, fillBlank, answer, image, custom];

export const registry = {
  all: modules,
  get(type){ return modules.find(m => m.type === type); },
  list(){ return modules; }
};
