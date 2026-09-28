module miter (
  input  [  0:0] \__pi_clk ,
  input  [  4:0] \__pi_datain ,
  input  [  0:0] \__pi_ena ,
  input  [  0:0] \__pi_reset_n ,
`ifdef DIRECT_CROSS_POINTS
`else
`endif
  output [  0:0] \__po_datain_5bis7__gold ,
  output [  0:0] \__po_datain_5bis7__gate
);
  \gold.test4.datain_5bis7 gold (
    .\__pi_clk (\__pi_clk ),
    .\__pi_datain (\__pi_datain ),
    .\__pi_ena (\__pi_ena ),
    .\__pi_reset_n (\__pi_reset_n ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_datain_5bis7 (\__po_datain_5bis7__gold )
  );
  \gate.test4.datain_5bis7 gate (
    .\__pi_clk (\__pi_clk ),
    .\__pi_datain (\__pi_datain ),
    .\__pi_ena (\__pi_ena ),
    .\__pi_reset_n (\__pi_reset_n ),
`ifdef DIRECT_CROSS_POINTS
`else
`endif
    .\__po_datain_5bis7 (\__po_datain_5bis7__gate )
  );
`ifdef ASSUME_DEFINED_INPUTS
  miter_def_prop #(1, "assume") \__pi_clk__assume (\__pi_clk );
  miter_def_prop #(5, "assume") \__pi_datain__assume (\__pi_datain );
  miter_def_prop #(1, "assume") \__pi_ena__assume (\__pi_ena );
  miter_def_prop #(1, "assume") \__pi_reset_n__assume (\__pi_reset_n );
`endif
`ifndef DIRECT_CROSS_POINTS
`endif
`ifdef CHECK_MATCH_POINTS
`endif
`ifdef CHECK_OUTPUTS
  miter_cmp_prop #(1, "assert") \__po_datain_5bis7__assert (\__po_datain_5bis7__gold , \__po_datain_5bis7__gate );
`endif
`ifdef COVER_DEF_CROSS_POINTS
  `ifdef DIRECT_CROSS_POINTS
  `else
  `endif
`endif
`ifdef COVER_DEF_GOLD_MATCH_POINTS
`endif
`ifdef COVER_DEF_GATE_MATCH_POINTS
`endif
`ifdef COVER_DEF_GOLD_OUTPUTS
  miter_def_prop #(1, "cover") \__po_datain_5bis7__gold_cover (\__po_datain_5bis7__gold );
`endif
`ifdef COVER_DEF_GATE_OUTPUTS
  miter_def_prop #(1, "cover") \__po_datain_5bis7__gate_cover (\__po_datain_5bis7__gate );
`endif
endmodule
module miter_cmp_prop #(parameter WIDTH=1, parameter TYPE="assert") (input [WIDTH-1:0] in_gold, in_gate);
  reg okay;
  integer i;
  always @* begin
    okay = 1;
    for (i = 0; i < WIDTH; i = i+1)
      okay = okay && (in_gold[i] === 1'bx || in_gold[i] === in_gate[i]);
  end
  generate
    if (TYPE == "assert") always @* assert(okay);
    if (TYPE == "assume") always @* assume(okay);
    if (TYPE == "cover")  always @* cover(okay);
  endgenerate
endmodule
module miter_def_prop #(parameter WIDTH=1, parameter TYPE="assert") (input [WIDTH-1:0] in);
  wire okay = ^in !== 1'bx;
  generate
    if (TYPE == "assert") always @* assert(okay);
    if (TYPE == "assume") always @* assume(okay);
    if (TYPE == "cover")  always @* cover(okay);
  endgenerate
endmodule
module \gold.test4.datain_5bis7 (
  input  [  0:0] \__pi_clk ,
  input  [  4:0] \__pi_datain ,
  input  [  0:0] \__pi_ena ,
  input  [  0:0] \__pi_reset_n ,
  output [  0:0] \__po_datain_5bis7
);
endmodule
module \gate.test4.datain_5bis7 (
  input  [  0:0] \__pi_clk ,
  input  [  4:0] \__pi_datain ,
  input  [  0:0] \__pi_ena ,
  input  [  0:0] \__pi_reset_n ,
  output [  0:0] \__po_datain_5bis7
);
endmodule
