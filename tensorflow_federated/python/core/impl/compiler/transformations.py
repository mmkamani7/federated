# Lint as: python3
# Copyright 2019, The TensorFlow Federated Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contains composite transformations, upon which higher compiler levels depend."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow_federated.python.common_libs import py_typecheck
from tensorflow_federated.python.core.impl import transformations
from tensorflow_federated.python.core.impl.compiler import building_blocks
from tensorflow_federated.python.core.impl.compiler import transformation_utils


def prepare_for_rebinding(comp):
  """Prepares `comp` for extracting rebound variables.

  Currently, this means replacing all called lambdas and inlining all blocks.
  This does not necessarly guarantee that the resulting computation has no
  called lambdas, it merely reduces a level of indirection here. This reduction
  has proved sufficient for identifying variables which are about to be rebound
  in the top-level lambda, necessarily when compiler components factor work out
  from a single function into multiple functions. Since this function makes no
  guarantees about sufficiency, it is the responsibility of the caller to
  ensure that no unbound variables are introduced during the rebinding.

  Args:
    comp: Instance of `building_blocks.ComputationBuildingBlock` from which all
      occurrences of a given variable need to be extracted and rebound.

  Returns:
    Another instance of `building_blocks.ComputationBuildingBlock` which has
    had all called lambdas replaced by blocks, all blocks inlined and all
    selections from tuples collapsed.
  """
  # TODO(b/146430051): Follow up here and consider removing or enforcing more
  # strict output invariants when `remove_lambdas_and_blocks` is moved in here.
  py_typecheck.check_type(comp, building_blocks.ComputationBuildingBlock)
  comp, _ = transformations.uniquify_reference_names(comp)
  comp, _ = transformations.replace_called_lambda_with_block(comp)
  block_inliner = transformations.InlineBlock(comp)
  selection_replacer = transformations.ReplaceSelectionFromTuple()
  transforms = [block_inliner, selection_replacer]
  symbol_tree = transformation_utils.SymbolTree(
      transformation_utils.ReferenceCounter)

  def _transform_fn(comp, symbol_tree):
    """Transform function chaining inlining and collapsing selections."""
    modified = False
    for transform in transforms:
      if transform.global_transform:
        comp, transform_modified = transform.transform(comp, symbol_tree)
      else:
        comp, transform_modified = transform.transform(comp)
      modified = modified or transform_modified
    return comp, modified

  return transformation_utils.transform_postorder_with_symbol_bindings(
      comp, _transform_fn, symbol_tree)


def remove_lambdas_and_blocks(comp):
  """Removes any called lambdas and blocks from `comp`.

  This function will rename all the variables in `comp` in a single walk of the
  AST, then replace called lambdas with blocks in another walk, since this
  transformation interacts with scope in delicate ways. It will chain inlining
  the blocks and collapsing the selection-from-tuple pattern together into a
  final pass.

  Args:
    comp: Instance of `building_blocks.ComputationBuildingBlock` from which we
      want to remove called lambdas and blocks.

  Returns:
    A transformed version of `comp` which has no called lambdas or blocks, and
    no extraneous selections from tuples.
  """
  py_typecheck.check_type(comp, building_blocks.ComputationBuildingBlock)

  # TODO(b/146057105): Follow up here with formal argument for why sufficiency
  # of two passes.
  modified = False
  for fn in [
      transformations.remove_unused_block_locals,
      transformations.inline_selections_from_tuple,
      transformations.replace_called_lambda_with_block,
  ] * 2:
    comp, inner_modified = fn(comp)
    modified = inner_modified or modified
  for fn in [
      transformations.remove_unused_block_locals,
      transformations.uniquify_reference_names,
  ]:
    comp, inner_modified = fn(comp)
    modified = inner_modified or modified

  block_inliner = transformations.InlineBlock(comp)
  selection_replacer = transformations.ReplaceSelectionFromTuple()
  transforms = [block_inliner, selection_replacer]

  def _transform_fn(comp, symbol_tree):
    """Transform function chaining inlining and collapsing selections.

    This function is inlined here as opposed to factored out and parameterized
    by the transforms to apply, due to the delicacy of chaining transformations
    which rely on state. These transformations should be safe if they appear
    first in the list of transforms, but due to the difficulty of reasoning
    about the invariants the transforms can rely on in this setting, there is
    no function exposed which hoists out the internal logic.

    Args:
      comp: Instance of `building_blocks.ComputationBuildingBlock` we wish to
        check for inlining and collapsing of selections.
      symbol_tree: Instance of `building_blocks.SymbolTree` defining the
        bindings available to `comp`.

    Returns:
      A transformed version of `comp`.
    """
    modified = False
    for transform in transforms:
      if transform.global_transform:
        comp, transform_modified = transform.transform(comp, symbol_tree)
      else:
        comp, transform_modified = transform.transform(comp)
      modified = modified or transform_modified
    return comp, modified

  symbol_tree = transformation_utils.SymbolTree(
      transformation_utils.ReferenceCounter)
  transformed_comp, inner_modified = transformation_utils.transform_postorder_with_symbol_bindings(
      comp, _transform_fn, symbol_tree)
  modified = modified or inner_modified
  return transformed_comp, modified
