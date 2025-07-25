#!/usr/bin/env python3
"""
Protein Bond Modeling Script

This script processes AlphaFold3 JSON files to model protein-protein bonds 
using ligand bridges. It identifies bonds between protein chains and modifies 
the structure to represent these bonds through intermediate ligand molecules.

The algorithm works by:
1. Identifying protein-protein bonds from bondedAtomPairs
2. Converting one of the bonded amino acids into a ligand molecule
3. Splitting the original chain and creating new chain segments
4. Establishing bonds through the ligand as an intermediate bridge

This approach allows modeling of complex protein interactions while maintaining
proper chemical connectivity through ligand intermediates.

Usage:
    python model_protein_bonds_hack.py --source-dir input/ --output-dir output/
    python model_protein_bonds_hack.py -s input/ -o output/ --verbose

Author: Ricardo Heinzmann
"""

import json
import os
import argparse
import traceback
from pathlib import Path
from typing import Dict, List, Tuple, Any
from copy import deepcopy

def load_json_files(source_dir: str) -> Dict[str, Dict]:
    """
    Load all JSON files from the specified directory.
    
    Args:
        source_dir: Directory containing JSON files
        
    Returns:
        Dictionary mapping filenames to their JSON content
    """
    json_files = {}
    source_path = Path(source_dir)
    
    if not source_path.exists():
        print(f"Warning: Directory {source_dir} does not exist")
        return json_files
    
    for json_file in source_path.glob("*.json"):
        try:
            with open(json_file, 'r') as f:
                json_files[json_file.stem] = json.load(f)
            print(f"Loaded: {json_file.name}")
        except Exception as e:
            print(f"Error loading {json_file.name}: {e}")
    
    return json_files

def initialize_residue_mapping(json_data: Dict) -> Dict[str, Dict[int, Dict[str, Any]]]:
    """
    Initialize a dictionary structure that maps every amino acid in every chain 
    to its modified id and residue number.
    
    Args:
        json_data: The AlphaFold3 JSON structure
        
    Returns:
        Dictionary mapping {chain_id: {residue_num: {modified_chain_id, modified_residue_num}}}
    """
    residue_mapping = {}
    
    for sequence in json_data.get("sequences", []):
        if "protein" in sequence:
            chain_id = sequence["protein"]["id"]
            sequence_length = len(sequence["protein"]["sequence"])
            
            residue_mapping[chain_id] = {}
            for i in range(1, sequence_length + 1):
                residue_mapping[chain_id][i] = {
                    "modified_chain_id": chain_id,
                    "modified_residue_num": i
                }
    
    return residue_mapping

def find_protein_protein_bonds(json_data: Dict) -> List[Tuple]:
    """
    Identify bonds between protein chains from bondedAtomPairs.
    
    Scans through all bonded atom pairs in the AlphaFold3 structure and identifies
    bonds that occur between protein chains (inter-chain) or within the same 
    protein chain (intra-chain). Both types are considered for ligand bridge modeling.
    
    Args:
        json_data: The AlphaFold3 JSON structure containing sequences and bonds
        
    Returns:
        List of tuples representing protein-protein bonds, where each tuple contains
        two bond endpoints: ((chain1, residue1, atom1), (chain2, residue2, atom2))
    """
    protein_bonds = []
    
    # Get protein chain IDs
    protein_chains = set()
    for sequence in json_data.get("sequences", []):
        if "protein" in sequence:
            protein_chains.add(sequence["protein"]["id"])
    
    # Check bondedAtomPairs for protein bonds (both inter and intra-chain)
    for bond in json_data.get("bondedAtomPairs", []):
        if len(bond) == 2:
            chain1, _, _ = bond[0]
            chain2, _, _ = bond[1]
            
            # Include bonds between protein chains AND within the same protein chain
            if chain1 in protein_chains and chain2 in protein_chains:
                protein_bonds.append(tuple(bond))
                if chain1 == chain2:
                    print(f"Found intra-chain bond: {chain1} (internal)")
                else:
                    print(f"Found inter-chain bond: {chain1} -> {chain2}")
    
    return protein_bonds

def get_sequence_info(json_data: Dict, chain_id: str) -> Dict:
    """
    Get sequence information for a specific chain.
    
    Args:
        json_data: The AlphaFold3 JSON structure
        chain_id: Chain identifier
        
    Returns:
        Dictionary with sequence information
    """
    for sequence in json_data.get("sequences", []):
        if "protein" in sequence and sequence["protein"]["id"] == chain_id:
            return sequence["protein"]
    return {}

def is_terminal_residue(sequence: str, residue_position: int) -> bool:
    """
    Check if a residue is at the terminal ends of a protein chain.
    
    Args:
        sequence: Protein sequence
        residue_position: 1-based position of the residue
        
    Returns:
        True if residue is at N-terminus (position 1) or C-terminus (last position)
    """
    return residue_position == 1 or residue_position == len(sequence)

def update_residue_mapping_for_terminal_split(residue_mapping: Dict, split_chain_id, split_chain_id_orig,
                                                 ligand_seq_num, ligand_seq_num_old,sequence_length: int,
                                            is_c_terminal: bool, new_chain_id) -> None:
    """
    Update residue mapping when splitting a chain at terminal position.
    
    When a terminal amino acid is converted to a ligand, this function updates
    the residue mapping to reflect the new chain structure. For C-terminal splits,
    the chain is shortened by removing the last residue. For N-terminal splits,
    the first residue becomes a ligand and remaining residues are renumbered.
    
    Args:
        residue_mapping: Dictionary tracking original to modified residue mappings
        split_chain_id: Current chain ID being split (e.g. AAB, BAA)
        split_chain_id_orig: Original chain ID from input structure (e.g. A, B)
        ligand_seq_num: Position of residue becoming ligand (in new numbering)
        ligand_seq_num_old: Position of residue becoming ligand (in original numbering)
        sequence_length: Length of the original chain sequence
        is_c_terminal: True if splitting at C-terminus, False for N-terminus
        new_chain_id: ID for the resulting chain after ligand removal
    """
    if is_c_terminal:
        # C-terminal split: chain keeps positions 1 to split_position-1
        # Ligand gets the last residue
        basepos = ligand_seq_num_old - sequence_length
        for pos in range(1, ligand_seq_num):
            residue_mapping[split_chain_id_orig][basepos + pos]["modified_chain_id"] = new_chain_id
            residue_mapping[split_chain_id_orig][basepos + pos]["modified_residue_num"] = pos
        
        # The terminal residue becomes ligand
        residue_mapping[split_chain_id_orig][ligand_seq_num]["modified_chain_id"] = f"{split_chain_id}L"
        residue_mapping[split_chain_id_orig][ligand_seq_num]["modified_residue_num"] = 1
    else:
        # N-terminal split: first residue becomes ligand, rest shifts down
        residue_mapping[split_chain_id_orig][ligand_seq_num_old]["modified_chain_id"] = f"{split_chain_id}L"
        residue_mapping[split_chain_id_orig][ligand_seq_num_old]["modified_residue_num"] = 1
        basepos = ligand_seq_num_old
        for pos in range(1, sequence_length):
            residue_mapping[split_chain_id_orig][basepos + pos]["modified_chain_id"] = new_chain_id
            residue_mapping[split_chain_id_orig][basepos + pos]["modified_residue_num"] = pos

def update_residue_mapping_for_internal_split(residue_mapping, split_chain_id, split_chain_id_orig,
                                                ligand_seq_num, ligand_seq_num_old, ligand_length) -> None:
    """
    Update residue mapping when splitting a chain at an internal position.
    
    When an internal amino acid is converted to a ligand, the original chain
    is split into two parts (A and B) with the ligand (L) as a bridge between them.
    This function updates the residue mapping to reflect this three-way split.
    
    Args:
        residue_mapping: Dictionary tracking original to modified residue mappings
        split_chain_id: Current chain ID being split
        split_chain_id_orig: Original chain ID from input structure
        ligand_seq_num: Position of residue becoming ligand (in new numbering)
        ligand_seq_num_old: Position of residue becoming ligand (in original numbering)
        ligand_length: Total length of the original chain sequence
    """
    basepos = ligand_seq_num_old - ligand_seq_num
    # Part A: residues 1 to split_position-1
    for pos in range(1, ligand_seq_num):
        residue_mapping[split_chain_id_orig][basepos + pos]["modified_chain_id"] = f"{split_chain_id}A"
        residue_mapping[split_chain_id_orig][basepos + pos]["modified_residue_num"] = pos
    
    # Ligand: the residue at split_position
    residue_mapping[split_chain_id_orig][basepos + ligand_seq_num]["modified_chain_id"] = f"{split_chain_id}L"
    residue_mapping[split_chain_id_orig][basepos + ligand_seq_num]["modified_residue_num"] = 1
    
    # Part B: residues split_position+1 to end
    for pos in range(ligand_seq_num + 1, ligand_length + 1):
        residue_mapping[split_chain_id_orig][basepos + pos]["modified_chain_id"] = f"{split_chain_id}B"
        residue_mapping[split_chain_id_orig][basepos + pos]["modified_residue_num"] = pos - ligand_seq_num

def model_bond_with_ligand(json_data: Dict, bond: Tuple, residue_mapping: Dict) -> Dict:
    """
    Modify JSON structure to model protein bond using a ligand bridge.
    Handles both inter-chain and intra-chain bonds.
    
    Args:
        json_data: Original AlphaFold3 JSON structure
        bond: Tuple representing the protein bond
        residue_mapping: Dictionary tracking residue mappings
        
    Returns:
        Modified JSON structure with ligand bridge
    """
    # Deep copy to avoid modifying original
    modified_json = deepcopy(json_data)
    
    # Extract bond information
    atom1, atom2 = bond
    chain1_id_orig, seq_num1_old, atom_name1 = atom1
    chain2_id_orig, seq_num2_old, atom_name2 = atom2
    
    # Check if this is an intra-chain bond
    is_intra_chain = chain1_id_orig == chain2_id_orig
    
    if is_intra_chain:
        print(f"Processing intra-chain bond in {chain1_id_orig}: residue {seq_num1_old} to {seq_num2_old}")
    else:
        print(f"Processing inter-chain bond: {chain1_id_orig} to {chain2_id_orig}")
    return process_chain_bond(modified_json, bond, is_intra_chain, residue_mapping, json_data)

def get_amino_acid_ccd_map():
    """Return the amino acid to CCD code mapping."""
    return {
        'G': 'GLY', 'A': 'ALA', 'V': 'VAL', 'L': 'LEU', 'I': 'ILE',
        'P': 'PRO', 'F': 'PHE', 'Y': 'TYR', 'W': 'TRP', 'S': 'SER',
        'T': 'THR', 'C': 'CYS', 'M': 'MET', 'N': 'ASN', 'Q': 'GLN',
        'D': 'ASP', 'E': 'GLU', 'K': 'LYS', 'R': 'ARG', 'H': 'HIS'
    }

def create_ligand_from_residue(chain_id: str, residue_char: str, ligand_suffix: str = "L") -> Dict:
    """
    Create a ligand sequence entry from an amino acid residue.
    
    Converts a single amino acid character into a ligand molecule entry
    using the appropriate CCD (Chemical Component Dictionary) code.
    
    Args:
        chain_id: Base chain identifier
        residue_char: Single letter amino acid code (e.g., 'A', 'G', 'L')
        ligand_suffix: Suffix to append to chain_id for ligand identification
        
    Returns:
        Dictionary representing a ligand sequence entry with CCD code
    """
    aa_to_ccd = get_amino_acid_ccd_map()
    ligand_ccd = aa_to_ccd.get(residue_char, 'UNK')
    
    return {
        "ligand": {
            "id": f"{chain_id}{ligand_suffix}",
            "ccdCodes": [ligand_ccd]
        }
    }

def create_protein_sequence(chain_id: str, sequence: str) -> Dict:
    """Create a protein sequence entry."""
    return {
        "protein": {
            "id": chain_id,
            "sequence": sequence
        }
    }

def add_peptide_bond(new_bonded_pairs: List, chain1_id: str, chain1_pos: int, chain2_id: str, chain2_pos: int):
    """
    Add a peptide bond between two chains.
    
    Creates a peptide bond by connecting the C-terminus of the first chain
    to the N-terminus of the second chain, following standard protein chemistry.
    
    Args:
        new_bonded_pairs: List to append the new bond to
        chain1_id: ID of the first chain (C-terminus)
        chain1_pos: Residue position in first chain
        chain2_id: ID of the second chain (N-terminus)
        chain2_pos: Residue position in second chain
    """
    new_bonded_pairs.append([[chain1_id, chain1_pos, "C"], [chain2_id, chain2_pos, "N"]])
    
def correct_chain_and_resnum(bondedAtomPairs, split_chain_id, ligand_seq_num, ligand_id, part_a_id, part_b_id):
    """
    Correct chain IDs and residue numbers in existing bonds after chain splitting.
    
    When a chain is split into parts (A, L, B), all existing bonds involving
    that chain need to be updated to use the new chain IDs and adjusted residue
    numbers. This function systematically updates all bond references.
    
    Args:
        bondedAtomPairs: List of existing bonded atom pairs to update
        split_chain_id: Original chain ID that was split
        ligand_seq_num: Position where the ligand was extracted
        ligand_id: New ID for the ligand molecule
        part_a_id: New ID for the first part of the split chain
        part_b_id: New ID for the second part of the split chain
        
    Returns:
        Updated list of bonded atom pairs with corrected chain IDs and positions
    """
    def helper(c,s):
        """Helper function to update chain ID and sequence number for bond correction."""
        if c == split_chain_id: # Bond involves the chain that was split
            if s == ligand_seq_num:
                # Bond to the ligand residue
                c, s = ligand_id, 1
            elif s < ligand_seq_num:
                # Bond to first part of chain (part A)
                c, s = part_a_id, s 
            else:
                # Bond to second part of chain (part B), adjust numbering
                c, s = part_b_id, s - ligand_seq_num
        return c, s
    new_bonded_atoms = []
    for pair in bondedAtomPairs:
        if len(pair) != 2:
            print(f"Warning: Skipping malformed bond pair {pair}")
            raise ValueError("Bonded atom pair must have exactly two elements")
        p1,p2 = pair
        [c1,s1,a1] = p1
        [c2,s2,a2] = p2 
        c1, s1 = helper(c1, s1)
        c2, s2 = helper(c2, s2)
        new_bonded_atoms.append([[c1, s1, a1], [c2, s2, a2]])
    return new_bonded_atoms

def process_chain_bond(modified_json: Dict, bond: Tuple, is_intra_chain: bool,residue_mapping: Dict, original_json: Dict) -> Dict:
    """
    Process protein-protein bonds by converting amino acids to ligand bridges.
    
    This is the core function that implements the ligand bridge modeling algorithm.
    It decides which amino acid to convert to a ligand (preferring terminal residues),
    splits the chain appropriately, creates the ligand molecule, and establishes
    proper connectivity through the ligand intermediate.
    
    The algorithm handles two main cases:
    1. Terminal residues: Chain is shortened, ligand connects to remaining chain
    2. Internal residues: Chain splits into A-L-B structure with three connections
    
    Args:
        modified_json: JSON structure being modified
        bond: Tuple representing the protein bond to process
        is_intra_chain: Whether the bond is within the same chain
        residue_mapping: Dictionary tracking residue position mappings
        original_json: Original unmodified JSON structure
        
    Returns:
        Modified JSON structure with ligand bridge representation
    """
    atom1, atom2 = bond
    chain1_id_orig, seq_num1_old, atom_name1 = atom1
    chain2_id_orig, seq_num2_old, atom_name2 = atom2
    chain1_id = residue_mapping[chain1_id_orig][seq_num1_old]["modified_chain_id"]
    chain2_id = residue_mapping[chain2_id_orig][seq_num2_old]["modified_chain_id"]
    seq_num1 = residue_mapping[chain1_id_orig][seq_num1_old]["modified_residue_num"]
    seq_num2 = residue_mapping[chain2_id_orig][seq_num2_old]["modified_residue_num"]
    # Get sequence information
    chain1_info = get_sequence_info(modified_json, chain1_id)
    chain2_info = get_sequence_info(modified_json, chain2_id)
    
    if not chain1_info or not chain2_info:
        print(f"Warning: Could not find sequence info for chains {chain1_id_orig} or {chain2_id_orig}")
        return modified_json
    
    chain1_sequence = chain1_info["sequence"]
    chain2_sequence = chain2_info["sequence"]
    
    # Determine which residue to use as ligand (prefer terminal residues for simpler structure)
    chain1_is_terminal = is_terminal_residue(chain1_sequence, seq_num1)
    chain2_is_terminal = is_terminal_residue(chain2_sequence, seq_num2)
    use_chain1_for_split = chain1_is_terminal or not chain2_is_terminal
    
    new_sequences = []
    new_bonded_pairs = []
    
    if use_chain1_for_split:
        # Convert chain1 residue to ligand
        split_chain_id = chain1_id
        ligand_residue = chain1_sequence[seq_num1 - 1]
        split_chain_id_orig = chain1_id_orig
        ligand_seq_num_old = seq_num1_old
        ligand_seq_num = seq_num1
        ligand_atom_name = atom_name1
        target_chain_id = chain2_id
        target_chain_id_orig = chain2_id_orig
        target_seq_num_old = seq_num2_old
        target_seq_num = seq_num2
        target_atom_name = atom_name2
        split_chain_sequence = chain1_sequence
        is_ligand_terminal = chain1_is_terminal
    else:
        # Convert chain2 residue to ligand
        split_chain_id = chain2_id
        ligand_seq_num = seq_num2
        split_chain_id_orig = chain2_id_orig
        ligand_seq_num_old = seq_num2_old
        ligand_residue = chain2_sequence[seq_num2 - 1]
        ligand_atom_name = atom_name2
        target_chain_id = chain1_id
        target_chain_id_orig = chain1_id_orig
        target_seq_num = seq_num1
        target_seq_num_old = seq_num1_old
        target_atom_name = atom_name1
        split_chain_sequence = chain2_sequence
        is_ligand_terminal = chain2_is_terminal
    
    # Create ligand from selected amino acid
    ligand_id = f"{split_chain_id}L"
    new_sequences.append(create_ligand_from_residue(split_chain_id, ligand_residue))
    
    # Handle chain splitting based on ligand position
    # Terminal: Chain -> Chain + Ligand (2 parts)
    # Internal: Chain -> ChainA + Ligand + ChainB (3 parts)
    if is_ligand_terminal:
        is_c_terminal = ligand_seq_num == len(split_chain_sequence)
        
        if is_c_terminal:
            new_chain_id = f"{split_chain_id}A"
            modified_sequence = split_chain_sequence[:-1]
        else:
            new_chain_id = f"{split_chain_id}B"
            modified_sequence = split_chain_sequence[1:]
        
        if modified_sequence:
            new_sequences.append(create_protein_sequence(new_chain_id, modified_sequence))
            
            # Add peptide bonds
            if is_c_terminal:
                add_peptide_bond(new_bonded_pairs, new_chain_id, len(modified_sequence), ligand_id, 1)
            else:
                add_peptide_bond(new_bonded_pairs, ligand_id, 1, new_chain_id, 1)        
        
        update_residue_mapping_for_terminal_split(residue_mapping, split_chain_id, split_chain_id_orig,
                                                ligand_seq_num, ligand_seq_num_old, len(split_chain_sequence), is_c_terminal, new_chain_id)
    else:
        # Internal residue - split into two parts
        update_residue_mapping_for_internal_split(residue_mapping, split_chain_id, split_chain_id_orig,
                                                ligand_seq_num, ligand_seq_num_old, len(split_chain_sequence))
        
        part_a_sequence = split_chain_sequence[:ligand_seq_num-1]
        part_b_sequence = split_chain_sequence[ligand_seq_num:]
        
        if part_a_sequence:
            part_a_id = f"{split_chain_id}A"
            new_sequences.append(create_protein_sequence(part_a_id, part_a_sequence))
            add_peptide_bond(new_bonded_pairs, part_a_id, len(part_a_sequence), ligand_id, 1)
        
        if part_b_sequence:
            part_b_id = f"{split_chain_id}B"
            new_sequences.append(create_protein_sequence(part_b_id, part_b_sequence))
            add_peptide_bond(new_bonded_pairs, ligand_id, 1, part_b_id, 1)
    
    
    # Add other sequences unchanged (excluding the ligand chain)
    for sequence in modified_json["sequences"]:
        if "protein" in sequence and sequence["protein"]["id"] != split_chain_id:
            new_sequences.append(sequence)
        elif "ligand" in sequence or "dna" in sequence or "rna" in sequence:
            new_sequences.append(sequence)
    
    # Bond from ligand to target chain
    target_mapped = residue_mapping[target_chain_id_orig][target_seq_num_old]
    new_bonded_pairs.append([[ligand_id, 1, ligand_atom_name], 
                           [target_mapped["modified_chain_id"], 
                            target_mapped["modified_residue_num"], target_atom_name]])
    
    # Add existing bonds (excluding the original bond being replaced)
    bond_new = [[chain1_id, seq_num1, atom_name1],[chain2_id, seq_num2, atom_name2]]
    for existing_bond in modified_json.get("bondedAtomPairs", []):
        if existing_bond != bond_new:
            new_bonded_pairs.append(existing_bond)
    
    # Correct existing bonds to use new chain IDs and residue numbering
    if is_ligand_terminal:
        part_a_id, part_b_id = f"{split_chain_id}A", f"{split_chain_id}B"
        new_bonded_pairs = correct_chain_and_resnum(new_bonded_pairs, split_chain_id, ligand_seq_num, ligand_id, part_a_id, part_b_id)
    else:
        new_bonded_pairs = correct_chain_and_resnum(new_bonded_pairs, split_chain_id, ligand_seq_num, ligand_id, part_a_id, part_b_id)
        
    modified_json["sequences"] = new_sequences
    modified_json["bondedAtomPairs"] = new_bonded_pairs
    return modified_json

def process_json_files(source_dir: str, output_dir: str) -> None:
    """
    Process all JSON files in the source directory and create modified versions.
    
    Args:
        source_dir: Directory containing original JSON files
        output_dir: Directory to save modified JSON files
    """
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Load all JSON files
    json_files = load_json_files(source_dir)
    
    for filename, json_data in json_files.items():
        print(f"\nProcessing {filename}...")
        
        # Initialize residue mapping
        residue_mapping = initialize_residue_mapping(json_data)
        
        # Find protein-protein bonds
        protein_bonds = find_protein_protein_bonds(json_data)
        
        if not protein_bonds:
            print(f"No protein-protein bonds found in {filename}")
            continue
        
        # Process each protein-protein bond
        modified_json = json_data
        for i, bond in enumerate(protein_bonds, 1):
            print(f"Modifying bond {i}/{len(protein_bonds)}: {bond}")
            modified_json = model_bond_with_ligand(modified_json, bond, residue_mapping)
        
        # Save modified JSON
        output_path = Path(output_dir) / f"{filename}.json"
        with open(output_path, 'w') as f:
            json.dump(modified_json, f, indent=2)
        
        print(f"Saved modified file: {output_path}")

def main():
    """
    Main function to execute the protein bond modeling script.
    """
    parser = argparse.ArgumentParser(
        description="Model protein-protein bonds using ligand bridges in AlphaFold3 JSON files"
    )
    parser.add_argument(
        "--source-dir", 
        "-s", 
        default="input/",
        help="Directory containing input JSON files (default: input/)"
    )
    parser.add_argument(
        "--output-dir", 
        "-o", 
        default="output/",
        help="Directory to save modified JSON files (default: output/)"
    )
    parser.add_argument(
        "--verbose", 
        "-v", 
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    print("Starting protein bond modeling process...")
    print(f"Source directory: {args.source_dir}")
    print(f"Output directory: {args.output_dir}")
    
    if args.verbose:
        print("Verbose mode enabled")
    
    # Check if source directory exists
    if not Path(args.source_dir).exists():
        print(f"Error: Source directory '{args.source_dir}' does not exist!")
        return 1
    
    # Process all JSON files
    process_json_files(args.source_dir, args.output_dir)
    print("Process completed successfully!")
    return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)