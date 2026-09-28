module decoder_5_1(input [4:0] sel,input [255:0] data,output reg [7:0] y,z);
always @* begin
y=8'h59;z=8'ha6;
case(sel)
5'd18: begin y=data[144 +: 8]; z=data[152 +: 8]; end
5'd17: begin y=data[136 +: 8]; z=data[128 +: 8]; end
5'd20: begin y=data[160 +: 8]; z=data[168 +: 8]; end
5'd24: begin y=data[192 +: 8]; z=data[200 +: 8]; end
5'd3: begin y=data[24 +: 8]; z=data[16 +: 8]; end
5'd10: begin y=data[80 +: 8]; z=data[88 +: 8]; end
5'd6: begin y=data[48 +: 8]; z=data[56 +: 8]; end
5'd22: begin y=data[176 +: 8]; z=data[184 +: 8]; end
5'd21: begin y=data[168 +: 8]; z=data[160 +: 8]; end
5'd0: begin y=data[0 +: 8]; z=data[8 +: 8]; end
5'd23: begin y=data[184 +: 8]; z=data[176 +: 8]; end
5'd9: begin y=data[72 +: 8]; z=data[64 +: 8]; end
5'd5: begin y=data[40 +: 8]; z=data[32 +: 8]; end
5'd8: begin y=data[64 +: 8]; z=data[72 +: 8]; end
5'd14: begin y=data[112 +: 8]; z=data[120 +: 8]; end
5'd15: begin y=data[120 +: 8]; z=data[112 +: 8]; end
5'd26: begin y=data[208 +: 8]; z=data[216 +: 8]; end
5'd30: begin y=data[240 +: 8]; z=data[248 +: 8]; end
5'd13: begin y=data[104 +: 8]; z=data[96 +: 8]; end
5'd12: begin y=data[96 +: 8]; z=data[104 +: 8]; end
5'd11: begin y=data[88 +: 8]; z=data[80 +: 8]; end
5'd28: begin y=data[224 +: 8]; z=data[232 +: 8]; end
5'd19: begin y=data[152 +: 8]; z=data[144 +: 8]; end
5'd1: begin y=data[8 +: 8]; z=data[0 +: 8]; end
5'd29: begin y=data[232 +: 8]; z=data[224 +: 8]; end
5'd7: begin y=data[56 +: 8]; z=data[48 +: 8]; end
5'd25: begin y=data[200 +: 8]; z=data[192 +: 8]; end
5'd27: begin y=data[216 +: 8]; z=data[208 +: 8]; end
5'd4: begin y=data[32 +: 8]; z=data[40 +: 8]; end
5'd2: begin y=data[16 +: 8]; z=data[24 +: 8]; end
5'd16: begin y=data[128 +: 8]; z=data[136 +: 8]; end
endcase
end
endmodule
